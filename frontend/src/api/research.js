import {request,post} from './client.js';
export const studies={list:()=>request('/studies'),create:x=>post('/studies',x),rows:id=>request(`/studies/${id}/observations`),save:(id,x,row)=>row?request(`/studies/${id}/observations/${row}`,{method:'PUT',body:JSON.stringify(x)}):post(`/studies/${id}/observations`,x),remove:(id,row)=>request(`/studies/${id}/observations/${row}`,{method:'DELETE'})};
export const runs={list:()=>request('/runs'),create:x=>post('/runs',x),get:id=>request(`/runs/${id}`),review:(id,note)=>post(`/runs/${id}/review`,{note}),export:id=>request(`/runs/${id}/export`)};
export const sequential={
  list:()=>request('/sequential/plans'),
  create:x=>post('/sequential/plans',x),
  get:id=>request(`/sequential/plans/${id}`),
  unblind:(id,stage,x)=>post(`/sequential/plans/${id}/looks/${stage}/unblind`,x),
  correct:(id,stage,x)=>post(`/sequential/plans/${id}/looks/${stage}/correct`,x),
};
