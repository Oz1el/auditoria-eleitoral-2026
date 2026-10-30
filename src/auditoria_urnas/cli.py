"""Explicit command-line interface; national processing requires the pilot gate."""
from __future__ import annotations

import argparse
import json
import sys

from .common import UFS, emit, root, prepare_directories


def main():
    parser=argparse.ArgumentParser(description='Inventário e ingestão auditável dos arquivos locais do TSE 2026, segundo turno.')
    sub=parser.add_subparsers(dest='command',required=True)
    inv=sub.add_parser('inventariar');inv.add_argument('--online',action='store_true')
    val=sub.add_parser('validar');val.add_argument('--uf',choices=UFS,required=True)
    sub.add_parser('piloto')
    pilot_comp=sub.add_parser('piloto-complementar');pilot_comp.add_argument('--workers',type=int,choices=[1,2,4],default=4)
    sub.add_parser('status-complementar')
    comp=sub.add_parser('processar-complementar')
    comp.add_argument('--workers',type=int,choices=[1,2,4],default=4)
    comp.add_argument('--ufs',nargs='+',choices=UFS,default=UFS)
    comp.add_argument('--etapas',nargs='+',choices=['rdv','logs','assinaturas','bweb','correspondencias','estatisticas','comparacoes','relatorios'],default=['rdv','logs','assinaturas','bweb','correspondencias','estatisticas','comparacoes','relatorios'])
    comp.add_argument('--simulacoes',type=int,choices=range(20,10001),default=1000)
    sub.add_parser('piloto-analise')
    ana=sub.add_parser('analisar');ana.add_argument('--simulations',type=int,choices=range(20,1001),default=100);ana.add_argument('--seed',type=int,default=20261025)
    proc=sub.add_parser('processar');proc.add_argument('--ufs',nargs='+',choices=UFS,default=UFS)
    sub.add_parser('status');sub.add_parser('relatorio');sub.add_parser('ambiente')
    dl=sub.add_parser('baixar-reposicoes')
    dl.add_argument('--ufs',nargs='+',choices=UFS,default=UFS)
    dl.add_argument('--confirmar-download',action='store_true',help='Operador confirma autorização do plano de reposição exibido anteriormente.')
    args=parser.parse_args()
    prepare_directories()
    try:
        if args.command=='inventariar':
            from .catalog import inventory
            value=inventory(args.online)
            emit('inventory_complete',present=value['present_regions'],eligible=value['readable_regions'])
        elif args.command=='validar':
            from .pipeline import validation
            inv=json.loads((root()/'data/catalog/inventory.json').read_text())
            row=next(x for x in inv['files'] if x['uf']==args.uf)
            if not row['eligible_for_validation']:raise ValueError('archive not eligible')
            validation(row)
        elif args.command=='piloto':
            from .pilot import run_pilot
            run_pilot()
        elif args.command=='piloto-complementar':
            from .complement import pilot
            pilot(workers=args.workers)
        elif args.command=='processar-complementar':
            from .complement import run
            value=run(args.ufs,args.etapas,args.simulacoes,workers=args.workers)
            if value['status']=='failed':return 2
        elif args.command=='status-complementar':
            path=root()/'data/checkpoints/latest-complement.json'
            value=json.loads(path.read_text()) if path.exists() else {'status':'not_started'}
            if value.get('status')=='running':
                from pathlib import Path
                try:
                    actual=Path(f"/proc/{value['pid']}/stat").read_text().rsplit(')',1)[1].split()[19]
                    value['process_alive']=actual==value.get('pid_start_ticks')
                except FileNotFoundError:value['process_alive']=False
                if not value['process_alive']:value['observed_status']='process_not_running; checkpoint retained; inspect service log'
            print(json.dumps(value,ensure_ascii=False,indent=2))
        elif args.command=='piloto-analise':
            from .analysis import pilot
            pilot()
        elif args.command=='analisar':
            from .analysis import execute
            execute(seed=args.seed,simulations=args.simulations)
        elif args.command=='processar':
            from .pipeline import process
            run=process(args.ufs)
            if run['failures']:
                return 2
        elif args.command=='ambiente':
            from .report import environment
            environment()
        elif args.command=='relatorio':
            from .report import reports
            emit('reports_created',**reports())
        elif args.command=='status':
            latest=root()/'data/checkpoints/latest-run.json'
            if not latest.exists():
                emit('status',status='no_national_run_started')
            else:
                run=json.loads(latest.read_text())
                print(json.dumps(json.loads(open(run['path']).read()),indent=2,ensure_ascii=False))
        elif args.command=='baixar-reposicoes':
            from .acquire import acquire_missing
            acquire_missing(args.ufs, confirm=args.confirmar_download)
    except Exception as e:
        emit('command_failed',command=args.command,error=str(e))
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
