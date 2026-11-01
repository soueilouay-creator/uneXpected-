from __future__ import annotations
import argparse, json, sys
from decimal import Decimal
from .coordinator import Coordinator
from .models import RuntimeErrorBase
from trading_engine import BacktestConfig, TradingService

def _trading_parser(sub):
    root=sub.add_parser("trading",help="paper-only market research and simulation")
    commands=root.add_subparsers(dest="trading_cmd",required=True)
    commands.add_parser("health")
    scan=commands.add_parser("scan"); scan.add_argument("--symbols",nargs="+",required=True); scan.add_argument("--timeframe",choices=("1Day","15Min"),default="1Day"); scan.add_argument("--limit",type=int,default=100)
    risk=commands.add_parser("risk-check"); risk.add_argument("--payload",required=True,help="JSON object containing explicit account/risk inputs")
    backtest=commands.add_parser("backtest"); backtest.add_argument("symbol"); backtest.add_argument("--initial-cash",required=True); backtest.add_argument("--timeframe",choices=("1Day","15Min"),default="1Day"); backtest.add_argument("--limit",type=int,default=100); backtest.add_argument("--lookback",type=int,default=20)
    account=commands.add_parser("account-open"); account.add_argument("account_id"); account.add_argument("--initial-cash",required=True)
    portfolio=commands.add_parser("portfolio"); portfolio.add_argument("account_id")
    order=commands.add_parser("paper-order"); order.add_argument("account_id"); order.add_argument("symbol"); order.add_argument("side",choices=("buy","sell")); order.add_argument("quantity",type=int); order.add_argument("price_usd"); order.add_argument("--fees-usd",default="0"); order.add_argument("--idempotency-key",required=True)

def main(argv=None):
    p=argparse.ArgumentParser(prog='uneXpected-v7'); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('status'); sub.add_parser('list')
    run=sub.add_parser('run'); run.add_argument('agent_id'); run.add_argument('--objective',required=True); run.add_argument('--inputs',default='{}'); run.add_argument('--idempotency-key'); run.add_argument('--deadline',type=float,default=30.0)
    chain=sub.add_parser('chain'); chain.add_argument('agents',nargs='+'); chain.add_argument('--objective',required=True); chain.add_argument('--inputs',default='{}'); chain.add_argument('--max-handoffs',type=int,default=4)
    graph=sub.add_parser('graph'); graph.add_argument('--graph-json',required=True); graph.add_argument('--max-nodes',type=int,default=20)
    sub.add_parser('eval')
    _trading_parser(sub)
    args=p.parse_args(argv); c=None; trading=None
    try:
        if args.cmd=='trading':
            trading=TradingService.from_env()
            if args.trading_cmd=='health': out=trading.health()
            elif args.trading_cmd=='scan': out=trading.scan(args.symbols,args.timeframe,args.limit)
            elif args.trading_cmd=='risk-check': out=trading.risk_check(json.loads(args.payload))
            elif args.trading_cmd=='backtest':
                config=BacktestConfig(initial_cash=Decimal(args.initial_cash),lookback=args.lookback)
                out=trading.backtest(args.symbol,args.timeframe,args.limit,config)
            elif args.trading_cmd=='account-open': out=trading.open_account(args.account_id,args.initial_cash)
            elif args.trading_cmd=='portfolio': out=trading.portfolio(args.account_id)
            else: out=trading.paper_order(args.account_id,args.symbol,args.side,args.quantity,args.price_usd,args.fees_usd,args.idempotency_key)
        else:
            c=Coordinator()
            if args.cmd=='status': out=c.status()
            elif args.cmd=='list': out={'count':len(c.registry),'agents':c.list_agents()}
            elif args.cmd=='run': out=c.invoke(args.agent_id,args.objective,json.loads(args.inputs),idempotency_key=args.idempotency_key,deadline_seconds=args.deadline).to_dict()
            elif args.cmd=='chain': out={'results':[r.to_dict() for r in c.run_chain(args.agents,args.objective,json.loads(args.inputs),max_handoffs=args.max_handoffs)]}
            elif args.cmd=='graph': out={'results':c.run_graph(json.loads(args.graph_json),max_nodes=args.max_nodes)}
            else:
                from .benchmark import BenchmarkRunner
                out=BenchmarkRunner().run().to_dict()
        print(json.dumps(out,indent=2,ensure_ascii=False,default=str)); return 0
    except Exception as e:
        print(json.dumps({'error':type(e).__name__,'message':str(e)}),file=sys.stderr); return 2
    finally:
        if c is not None: c.close()
        if trading is not None: trading.close()
if __name__=='__main__': raise SystemExit(main())
