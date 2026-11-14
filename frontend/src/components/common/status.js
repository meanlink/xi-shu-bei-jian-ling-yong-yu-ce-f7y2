import {JobStatus} from '../../constants/enums.js';
import {esc} from '../../utils/dom.js';
export const status=v=>'<span class="status '+esc(v)+'">'+esc(JobStatus[v]||v)+'</span>';
export const quarantineBadge=v=>v?'<span class="status quarantined">已隔离</span>':'';
