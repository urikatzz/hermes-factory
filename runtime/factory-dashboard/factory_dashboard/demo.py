"""Deterministic illustrative data for local UI and configuration demonstrations."""
from datetime import datetime, timezone
from .models import Snapshot


class DemoCollector:
    def __init__(self):
        self._now = datetime.now(timezone.utc).timestamp()

    def collect(self):
        start=self._now-540
        tasks=[{'id':'t_abc','title':'FACTORY: Add a side-by-side Markdown editor','status':'done','assignee':'planner','created_at':start,'completed_at':start+485},
               {'id':'t_aaa','title':'FACTORY: Improve workspace search','status':'blocked','assignee':'planner','created_at':start-5000,'completed_at':None,'block_kind':'review_required'}]
        runs=[];sessions=[];events=[]
        stages=[('t_100','PLAN','planner',0,125,'done','Plan accepted'),
                ('t_101','IMPLEMENT','builder',138,315,'done','Split editor with synchronized preview'),
                ('t_102','CODEX REVIEW','reviewer',322,404,'done','VERDICT=CHANGES_REQUIRED Add keyboard focus handling'),
                ('t_103','FIX','builder',410,450,'done','Keyboard navigation corrected'),
                ('t_104','VERIFY','reviewer',455,485,'done','VERDICT=PASS Browser and test evidence recorded')]
        models={'planner':'gpt-6-astra','builder':'gpt-6.1-sol','reviewer':'gpt-6-astra'}
        for i,(tid,title,role,begin,end,status,summary) in enumerate(stages,1):
            tasks.append({'id':tid,'title':f'{title} (t_abc)','status':status,'assignee':role,'created_at':start+begin,'completed_at':start+end})
            runs.append({'id':i,'task_id':tid,'profile':role,'status':status,'started_at':start+begin,'ended_at':start+end,'summary':summary,'metadata':{'worker_session_id':f'demo-{i}'}})
            sessions.append({'id':f'demo-{i}','profile':role,'database':f'demo/{role}','model':models[role],'billing_provider':'openai-codex','input_tokens':18000+i*2200,'output_tokens':1100+i*350,'cache_read_tokens':36000,'cache_write_tokens':None,'reasoning_tokens':400,'estimated_cost_usd':None,'actual_cost_usd':None,'cost_status':'included'})
            events.append({'id':i,'task_id':tid,'run_id':i,'kind':'completed','created_at':start+end,'payload':{'outcome':summary}})
        return Snapshot('demo',datetime.fromtimestamp(self._now,timezone.utc).isoformat(),(),tuple(tasks),tuple(runs),tuple(events),tuple(sessions),{},(),())


class DemoReportBuilder:
    def __init__(self, report_builder):
        self._builder=report_builder

    def build(self,snapshot):
        report=self._builder.build(snapshot)
        report['demo']=True
        return report


def demo_catalog():
    choices=[{'provider':'openai-codex','model':name} for name in ('gpt-6-astra','gpt-6.1-sol','gpt-6-luna')]
    return {'profiles':{role:{'default':choices[index], 'models':choices} for role,index in [('planner',0),('builder',1),('reviewer',0)]}}
