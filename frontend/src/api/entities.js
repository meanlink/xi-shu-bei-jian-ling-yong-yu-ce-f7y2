import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const quarantines={list:()=>api('/quarantines'),get:id=>api('/quarantines/'+id),create:data=>api('/quarantines',{method:'POST',body:JSON.stringify(data)}),replacement:(id,datasetId)=>api('/quarantines/'+id+'/replacement',{method:'POST',body:JSON.stringify({dataset_id:datasetId})})};
