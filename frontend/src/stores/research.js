import {studies,runs,sequential} from '../api/research.js';
export const store={studies:[],runs:[],plans:[],studyId:0,runId:0,rows:[]};
export async function load(){[store.studies,store.runs,store.plans]=await Promise.all([studies.list(),runs.list(),sequential.list()]);if(!store.studyId)store.studyId=store.studies[0]?.id||0;}
export async function loadRows(){store.rows=store.studyId?await studies.rows(store.studyId):[];}
