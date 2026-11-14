"""Isolation of a distorted issue calendar batch and its downstream impact.

The isolation boundary is the commit of the quarantine row. Every operation
that could publish something derived from the batch (job result write,
approval, delivery file write, archive download) takes the same dataset row
lock, so a request that completes after the boundary cannot reopen a result.
"""
import time
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.models import Dataset, Job, Report, Delivery, Quarantine
from src.constants.enums import JobStatus

FROZEN_JOB_STATUSES = (JobStatus.queued.value, JobStatus.running.value,
                       JobStatus.completed.value)


def lock_dataset(db, dataset_id):
    """Serialise against in-flight compute/delivery/download work.

    The select is issued with populate_existing so the returned row is read
    from the database under the lock rather than reused from the identity map.
    SQLite ignores FOR UPDATE but serialises write transactions itself.
    """
    return db.scalar(select(Dataset).where(Dataset.id == dataset_id).with_for_update()
                     .execution_options(populate_existing=True))


def for_dataset(db, dataset_id):
    return db.scalar(select(Quarantine).where(Quarantine.dataset_id == dataset_id))


def is_blocked(db, dataset_id):
    dataset = db.get(Dataset, dataset_id)
    return bool((dataset is not None and dataset.quarantined) or for_dataset(db, dataset_id))


def _affected_jobs(db, dataset_id):
    return list(db.scalars(select(Job).where(Job.dataset_id == dataset_id).order_by(Job.id)))


def _affected_reports(db, job_ids):
    if not job_ids:
        return []
    return list(db.scalars(select(Report).where(Report.job_id.in_(job_ids)).order_by(Report.id)))


def sweep(db, dataset, quarantine):
    """Stop and freeze everything derived from the quarantined batch.

    Existing results, plans and archives are retained for investigation, but
    approvals are revoked, plans stop running and downloads are blocked.
    """
    dataset.quarantined = True
    jobs = _affected_jobs(db, dataset.id)
    for job in jobs:
        job.approved = False
        job.quarantined = True
        if job.status in FROZEN_JOB_STATUSES:
            job.status = JobStatus.quarantined.value
    reports = _affected_reports(db, [j.id for j in jobs])
    for report in reports:
        report.enabled = False
        report.quarantined = True
        report.quarantine_id = quarantine.id
    if reports:
        report_ids = [r.id for r in reports]
        for delivery in db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids))):
            delivery.quarantined = True
            delivery.quarantine_id = quarantine.id
    return jobs, reports


def create(db, dataset, reason, actor):
    """Create the single quarantine record for a dataset.

    Returns (quarantine, created). A retry after a failed request reuses the
    committed record instead of inserting a second one, so accounting is not
    duplicated. The caller writes the audit entry in the same transaction.
    """
    reason = (reason or '').strip()
    if len(reason) < 5:
        raise HTTPException(422, '请填写至少 5 个字符的隔离原因')
    lock_dataset(db, dataset.id)
    existing = for_dataset(db, dataset.id)
    if existing:
        return existing, False
    now = time.time()
    quarantine = Quarantine(dataset_id=dataset.id, reason=reason[:500],
                            created_by=actor, created_at=now, effective_at=now)
    try:
        db.add(quarantine)
        db.flush()
    except IntegrityError:
        # Another request won the race; treat this attempt as a retry.
        db.rollback()
        lock_dataset(db, dataset.id)
        existing = for_dataset(db, dataset.id)
        if existing:
            return existing, False
        raise
    sweep(db, dataset, quarantine)
    return quarantine, True


def set_replacement(db, quarantine, dataset):
    if quarantine.replacement_dataset_id:
        if quarantine.replacement_dataset_id == dataset.id:
            return False
        raise HTTPException(409, '该问题批次已登记修正批次，如需再次修正请另建处置记录')
    if dataset.id == quarantine.dataset_id:
        raise HTTPException(409, '修正批次不能是原问题批次')
    if dataset.quarantined:
        raise HTTPException(409, '修正批次本身已被隔离，不能作为关联去向')
    if dataset.created_at < quarantine.created_at:
        raise HTTPException(409, '修正批次必须在隔离生效后另建')
    quarantine.replacement_dataset_id = dataset.id
    return True


def _replacement_state(db, quarantine):
    if not quarantine.replacement_dataset_id:
        return None
    dataset = db.get(Dataset, quarantine.replacement_dataset_id)
    if not dataset:
        return None
    jobs = list(db.scalars(select(Job).where(Job.dataset_id == dataset.id).order_by(Job.id.desc())))
    approved = next((j for j in jobs if j.approved and j.status == JobStatus.completed.value), None)
    report = None
    if approved:
        report = db.scalar(select(Report).where(Report.job_id == approved.id, Report.enabled == True,
                                                Report.quarantined == False).order_by(Report.id.desc()))
    deliveries = list(db.scalars(select(Delivery).where(Delivery.report_id == report.id).order_by(Delivery.id.desc()))) if report else []
    return {'dataset': dataset, 'jobs': jobs, 'approved_job': approved, 'report': report, 'deliveries': deliveries}


def summary(db, quarantine):
    dataset = db.get(Dataset, quarantine.dataset_id)
    jobs = _affected_jobs(db, quarantine.dataset_id)
    reports = _affected_reports(db, [j.id for j in jobs])
    report_ids = [r.id for r in reports]
    deliveries = list(db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids)).order_by(Delivery.id))) if report_ids else []
    replacement = _replacement_state(db, quarantine)
    steps = [{'key': 'quarantined', 'label': '隔离生效', 'done': True},
             {'key': 'replacement', 'label': '修正日历已另建批次', 'done': replacement is not None},
             {'key': 'approved', 'label': '修正批次已重新批准', 'done': bool(replacement and replacement['approved_job'])},
             {'key': 'distributed', 'label': '新分发计划已重新启用', 'done': bool(replacement and replacement['report'])}]
    current = next((s['key'] for s in steps if not s['done']), 'distributed')
    return {
        'id': quarantine.id, 'dataset_id': quarantine.dataset_id,
        'dataset_name': dataset.name if dataset else None,
        'reason': quarantine.reason, 'created_by': quarantine.created_by,
        'created_at': quarantine.created_at, 'effective_at': quarantine.effective_at,
        'replacement_dataset_id': quarantine.replacement_dataset_id,
        'replacement': ({'dataset_id': replacement['dataset'].id, 'dataset_name': replacement['dataset'].name,
                         'approved_job_id': replacement['approved_job'].id if replacement['approved_job'] else None,
                         'report_id': replacement['report'].id if replacement['report'] else None,
                         'delivery_ids': [d.id for d in replacement['deliveries']]} if replacement else None),
        'progress': {'steps': steps, 'current': current},
        'affected': {
            'jobs': [{'id': j.id, 'name': j.name, 'status': j.status, 'approved': j.approved,
                       'finished_at': j.finished_at, 'has_result': bool(j.result)} for j in jobs],
            'reports': [{'id': r.id, 'name': r.name, 'enabled': r.enabled, 'job_id': r.job_id,
                          'destination': r.destination, 'next_run': r.next_run} for r in reports],
            'deliveries': [{'id': d.id, 'filename': d.filename, 'report_id': d.report_id,
                             'created_at': d.created_at, 'destination': d.destination} for d in deliveries],
        },
        'counts': {'jobs': len(jobs), 'reports': len(reports), 'deliveries': len(deliveries)},
    }
