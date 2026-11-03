from __future__ import annotations
import argparse, json, sys, time
from .coordinator import Coordinator
from .models import RuntimeErrorBase
from .resource_intelligence import ResourceRegistry
from .quality_evaluation import QualityEvaluationRunner

def main(argv=None):
    p=argparse.ArgumentParser(prog='uneXpected-v7'); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('status'); sub.add_parser('list')
    run=sub.add_parser('run'); run.add_argument('agent_id'); run.add_argument('--objective',required=True); run.add_argument('--inputs',default='{}'); run.add_argument('--idempotency-key'); run.add_argument('--deadline',type=float,default=30.0)
    lifecycle=sub.add_parser('lifecycle'); lifecycle.add_argument('agent_id'); lifecycle.add_argument('--objective',required=True); lifecycle.add_argument('--inputs',default='{}'); lifecycle.add_argument('--max-corrections',type=int,default=1); lifecycle.add_argument('--max-improvements',type=int,default=3); lifecycle.add_argument('--deadline',type=float,default=60.0)
    chain=sub.add_parser('chain'); chain.add_argument('agents',nargs='+'); chain.add_argument('--objective',required=True); chain.add_argument('--inputs',default='{}'); chain.add_argument('--max-handoffs',type=int,default=4)
    graph=sub.add_parser('graph'); graph.add_argument('--graph-json',required=True); graph.add_argument('--max-nodes',type=int,default=20)
    resources=sub.add_parser('resources'); resources.add_argument('--category'); resources.add_argument('--status'); resources.add_argument('--validate',action='store_true')
    quality=sub.add_parser('quality-eval'); quality.add_argument('--provider-route'); quality.add_argument('--scenario',action='append',dest='scenario_ids')
    sub.add_parser('eval')
    media=sub.add_parser('media'); media_sub=media.add_subparsers(dest='media_cmd',required=True)
    media_sub.add_parser('status')
    media_jobs=media_sub.add_parser('jobs'); media_jobs.add_argument('--state'); media_jobs.add_argument('--limit',type=int,default=50)
    media_enqueue=media_sub.add_parser('enqueue'); media_enqueue.add_argument('--request-json',required=True)
    media_cancel=media_sub.add_parser('cancel'); media_cancel.add_argument('job_id')
    media_review=media_sub.add_parser('review'); media_review.add_argument('--reviewer',required=True); media_review.add_argument('--reason',required=True)
    media_install=media_sub.add_parser('install'); media_install.add_argument('--reason',required=True)
    media_preflight=media_sub.add_parser('preflight')
    media_enable=media_sub.add_parser('enable'); media_enable.add_argument('--reason',required=True)
    media_worker=media_sub.add_parser('worker'); media_worker.add_argument('--once',action='store_true',required=True)
    args=p.parse_args(argv); c=Coordinator(); exit_code=0
    try:
        if args.cmd=='status': out=c.status()
        elif args.cmd=='resources':
            registry=ResourceRegistry()
            out=registry.validate() if args.validate else {'summary':registry.summary(),'items':registry.list_resources(category=args.category,status=args.status)}
        elif args.cmd=='quality-eval':
            out=QualityEvaluationRunner(c).run(provider_route=args.provider_route,scenario_ids=args.scenario_ids)
            exit_code=0 if out.get('status')=='passed' else 3
        elif args.cmd=='media':
            if args.media_cmd=='status':
                out={'media':c.media_status()}
            elif args.media_cmd=='jobs':
                out={'count':len(c.media_list_jobs(limit=args.limit,state=args.state)),'items':c.media_list_jobs(limit=args.limit,state=args.state)}
            elif args.media_cmd=='enqueue':
                out=c.media_create_job(json.loads(args.request_json))
            elif args.media_cmd=='cancel':
                out=c.media_cancel_job(args.job_id)
            elif args.media_cmd=='review':
                out=c.capabilities.transition('media.openfilm.render','reviewed',reviewer=args.reviewer,reason=args.reason).to_dict()
            elif args.media_cmd=='install':
                out=c.capabilities.transition('media.openfilm.render','installed',reason=args.reason).to_dict()
            elif args.media_cmd in {'preflight','enable','worker'}:
                from .media.worker import MediaWorker, MediaWorkerConfig
                from .media.isolation import PodmanIsolation, PodmanIsolationConfig
                from .media.qa import MediaQualityAssurance
                if c.media_jobs is None:
                    raise RuntimeError('Media-job storage is unavailable.')
                worker_config=MediaWorkerConfig.from_env()
                isolation=PodmanIsolation(PodmanIsolationConfig.from_env())
                qa=MediaQualityAssurance.from_env()
                worker=MediaWorker(c.media_jobs,isolation,worker_config,qa=qa)
                isolation.validate_limits(worker._limits())
                if args.media_cmd=='preflight':
                    readiness=isolation.self_test()
                    out={'worker_readiness':readiness,'limits':'validated against configured host ceilings'}
                    if readiness.get('available') is True:
                        c.store.log_event('media_worker_preflight_passed',agent_id='media-worker',
                            payload={'config_sha256':c.media_worker_config_fingerprint(),
                                     'worker_image':isolation.config.image,'tested_at':time.time()})
                    else:
                        exit_code=3
                elif args.media_cmd=='enable':
                    readiness=isolation.self_test()
                    if readiness.get('available') is not True:
                        raise RuntimeError(readiness.get('reason','Worker host isolation self-test failed.'))
                    c.store.log_event('media_worker_preflight_passed',agent_id='media-worker',
                        payload={'config_sha256':c.media_worker_config_fingerprint(),
                                 'worker_image':isolation.config.image,'tested_at':time.time()})
                    c.media_register_adapter()
                    out=c.capabilities.transition('media.openfilm.render','enabled',reason=args.reason).to_dict()
                else:
                    record=c.capabilities.get('media.openfilm.render')
                    if record.status!='enabled':
                        raise RuntimeError('OpenFilm must be enabled after review, installation and a passing worker preflight.')
                    out=worker.run_once()
                    exit_code=0 if out.get('status') in {'idle','ready_for_human_review','cancelled'} else 3
        elif args.cmd=='list': out={'count':len(c.registry),'agents':c.list_agents()}
        elif args.cmd=='run': out=c.invoke(args.agent_id,args.objective,json.loads(args.inputs),idempotency_key=args.idempotency_key,deadline_seconds=args.deadline).to_dict()
        elif args.cmd=='lifecycle':
            out=c.run_lifecycle(args.agent_id,args.objective,json.loads(args.inputs),max_corrections=args.max_corrections,max_improvements=args.max_improvements,deadline_seconds=args.deadline).to_dict()
            exit_code=0 if out.get('status')=='delivered' and out.get('delivered') is True else 3
        elif args.cmd=='chain': out={'results':[r.to_dict() for r in c.run_chain(args.agents,args.objective,json.loads(args.inputs),max_handoffs=args.max_handoffs)]}
        elif args.cmd=='graph': out={'results':c.run_graph(json.loads(args.graph_json),max_nodes=args.max_nodes)}
        else:
            from .benchmark import BenchmarkRunner
            out=BenchmarkRunner().run().to_dict()
        print(json.dumps(out,indent=2,ensure_ascii=False)); return exit_code
    except Exception as e:
        print(json.dumps({'error':type(e).__name__,'message':str(e)}),file=sys.stderr); return 2
    finally: c.close()
if __name__=='__main__': raise SystemExit(main())
