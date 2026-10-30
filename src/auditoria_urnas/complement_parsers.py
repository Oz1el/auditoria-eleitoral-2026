"""Bounded parsers for RDV, nested logs and published signature containers.

No individual voter identifiers, vote ordering or raw log messages are exported.
Only section-level counters/timestamps leave this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections import Counter,defaultdict
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import asn1tools

from .analysis import municipality_zone
from .common import root

MAX_LOG_BYTES=128*1024**2


@lru_cache(maxsize=1)
def rdv_codec():
    return asn1tools.compile_files(str(root()/'specs/rdv.asn1'),codec='ber',numeric_enums=True)


@lru_cache(maxsize=1)
def signature_codec():
    return asn1tools.compile_files(str(root()/'specs/assinatura.asn1'),codec='ber',numeric_enums=True)


def decode_complete(codec,kind,raw):
    obj,n=codec.decode_with_length(kind,raw,check_constraints=True)
    if n!=len(raw):raise ValueError('trailing bytes in '+kind)
    return obj


def parse_rdv(raw,identity):
    obj=decode_complete(rdv_codec(),'EntidadeResultadoRDV',raw)
    r=obj['rdv'];ident=r['identificacao'];mz=ident['municipioZona']
    if (r['fase'],r['pleito'],mz['municipio'],mz['zona'],ident['secao'])!=(2,3221,*identity):
        raise ValueError('RDV identity/phase/pleito mismatch')
    result={'rdv_status':'ok','rdv_source':r['eleicoes'][0],'rdv_lula':0,'rdv_bolsonaro':0,'rdv_brancos':0,
            'rdv_nulos':0,'rdv_outros':0,'rdv_total':0,'rdv_cargos_encontrados':0,'rdv_tipos_json':'{}'}
    counts=Counter();candidates=Counter()
    for election in r['eleicoes'][1]:
        if election['idEleicao']!=6258:continue
        for office in election['votosCargos']:
            if office['idCargo']!=('cargoConstitucional',1):continue
            result['rdv_cargos_encontrados']+=1
            if office['quantidadeEscolhas']!=1:raise ValueError('unexpected presidential choices')
            for vote in office['votos']:
                t=vote['tipoVoto'];counts[t]+=1
                if t==2:
                    if 'digitacao' not in vote:raise ValueError('nominal RDV without digits')
                    candidates[int(vote['digitacao'])]+=1
    if result['rdv_cargos_encontrados']!=1:raise ValueError('missing/duplicated presidential RDV office')
    result.update(rdv_lula=candidates[13],rdv_bolsonaro=candidates[22],
                  rdv_brancos=counts[3]+counts[5],rdv_nulos=sum(counts[t] for t in [4,6,7,8,9]),
                  rdv_total=sum(counts.values()),rdv_tipos_json=json.dumps(dict(counts),sort_keys=True))
    result['rdv_outros']=result['rdv_total']-sum(result[k] for k in ['rdv_lula','rdv_bolsonaro','rdv_brancos','rdv_nulos'])
    if any(t not in range(1,10) for t in counts):raise ValueError('unknown RDV vote enum')
    return result


def summarize_log_lines(lines,zone,origin='dadosSecao',*,identity=None,seen_events=None):
    """Count terminal events only in explicitly marked second-round VOTA sessions."""
    result={'log_status':'ok','log_total_computados':0,'log_total_confirmados_presidente':0,
            'log_apos17':0 if zone and origin=='dadosSecao' else None,
            'log_17_18':0 if zone and origin=='dadosSecao' else None,
            'log_18_19':0 if zone and origin=='dadosSecao' else None,
            'log_apos19':0 if zone and origin=='dadosSecao' else None,
            'log_confirmacoes_apos17':0 if zone and origin=='dadosSecao' else None,
            'log_ultimo_computado_original':None,'log_ultimo_computado_brasilia':None,
            'log_encerramento_original':None,'log_encerramento_brasilia':None,
            'log_linhas_invalidas':0,'log_ajustes_relogio':0,'log_reinicios':0,'log_cancelamentos':0,
            'log_suspensoes':0,'log_habilitados':0,'log_biometricos':0,'log_manuais':0,
            'log_eventos_sem_turno':0,'log_sessoes_segundo_turno':0,'log_eventos_anteriores':0,
            'log_ordem_temporal_invertida':0,'log_contagem_temporal_confiavel':False}
    result.update(log_eventos_sem_identidade=0,log_eventos_outra_secao=0,log_eventos_duplicados_entre_arquivos=0,log_encerramentos_confirmados=0)
    turn=None;previous=None;current_identities=defaultdict(dict);turns={};local_events=Counter()
    for line_number,line in enumerate(lines,1):
        parts=line.rstrip('\r\n').split('\t',4)
        if len(parts)!=5:
            result['log_linhas_invalidas']+=1;continue
        stamp,level,device,app,tail=parts
        message=tail.rsplit('\t',1)[0]
        if message.startswith('Iniciando aplicação - '):
            m=re.search(r'([12])º turno',message)
            if m:
                turn=int(m[1]);turns[device]=turn
                if turn==2 and app=='VOTA':result['log_sessoes_segundo_turno']+=1
        # GAP records the configured section during preparation, often before voting day.
        if app in ['GAP','VOTA']:
            for label,field in [('Município','municipio'),('Zona Eleitoral','zona'),('Seção Eleitoral','secao')]:
                marker=re.fullmatch(re.escape(label)+r': (\d+)',message)
                if marker:current_identities[device][field]=int(marker[1])
        on_day=stamp.startswith(('25/10/2026 ','26/10/2026 '))
        if not on_day:
            result['log_eventos_anteriores']+=1;continue
        if re.search(r'(ajust|alter|atualiz).*(rel.gio|data.hora|hor.rio)|rel.gio.*(ajust|alter|atualiz)',message,re.I):result['log_ajustes_relogio']+=1
        if app!='VOTA':continue
        turn=turns.get(device)
        current_identity=current_identities.get(device,{})
        if turn!=2:
            if turn is None and message in ['O voto do eleitor foi computado','Voto confirmado para [Presidente]']:result['log_eventos_sem_turno']+=1
            continue
        if 'Iniciando aplicação' in message:result['log_reinicios']+=1
        if 'cancelad' in message.lower():result['log_cancelamentos']+=1
        if 'suspens' in message.lower() or 'suspenso' in message.lower():result['log_suspensoes']+=1
        if message=='Eleitor foi habilitado':result['log_habilitados']+=1
        if message=='Tipo de habilitação do eleitor [biométrica]':result['log_biometricos']+=1
        if message=='Tipo de habilitação do eleitor [manual]':result['log_manuais']+=1
        kind=('computed' if message=='O voto do eleitor foi computado' else
              'president' if message=='Voto confirmado para [Presidente]' else
              'closure' if message=='Procedimento de encerramento confirmado' else None)
        if kind is None:continue
        if identity is not None:
            observed=tuple(current_identity.get(k) for k in ['municipio','zona','secao'])
            if None in observed:
                result['log_eventos_sem_identidade']+=1;continue
            if observed!=tuple(identity):
                result['log_eventos_outra_secao']+=1;continue
        fingerprint=hashlib.sha256(line.rstrip('\r\n').encode('latin1')).hexdigest()
        local_events[fingerprint]+=1
        if seen_events is not None and seen_events.get(fingerprint,0)>=local_events[fingerprint]:
            result['log_eventos_duplicados_entre_arquivos']+=1;continue
        try:dt=datetime.strptime(stamp,'%d/%m/%Y %H:%M:%S')
        except ValueError:
            result['log_linhas_invalidas']+=1;continue
        if previous is not None and dt<previous:result['log_ordem_temporal_invertida']+=1
        previous=dt
        br=dt.replace(tzinfo=ZoneInfo(zone)).astimezone(ZoneInfo('America/Sao_Paulo')) if zone and origin=='dadosSecao' else None
        if kind=='computed':
            result['log_total_computados']+=1
            result['log_ultimo_computado_original']=dt.isoformat()
            result['log_ultimo_computado_brasilia']=br.isoformat() if br else None
            if br:
                second=br.hour*3600+br.minute*60+br.second
                late=(br.date()>datetime(2026,10,25).date()) or (br.date()==datetime(2026,10,25).date() and second>61200)
                if late:
                    result['log_apos17']+=1
                    if br.date()>datetime(2026,10,25).date() or second>68400:result['log_apos19']+=1
                    elif second>=64800:result['log_18_19']+=1
                    else:result['log_17_18']+=1
        elif kind=='president':
            result['log_total_confirmados_presidente']+=1
            if br and (br.date()>datetime(2026,10,25).date() or br.hour*3600+br.minute*60+br.second>61200):result['log_confirmacoes_apos17']+=1
        else:
            result['log_encerramentos_confirmados']+=1
            result['log_encerramento_original']=dt.isoformat()
            result['log_encerramento_brasilia']=br.isoformat() if br else None
    if origin!='dadosSecao':
        result['log_status']='sistema_apuracao_sem_horario_individual_inferido'
    result['log_contagem_temporal_confiavel']=bool(zone and origin=='dadosSecao' and result['log_sessoes_segundo_turno'] and
        not any(result[k] for k in ['log_linhas_invalidas','log_ajustes_relogio','log_eventos_sem_turno','log_ordem_temporal_invertida','log_eventos_sem_identidade']))
    if seen_events is not None:
        for fingerprint,count in local_events.items():seen_events[fingerprint]=max(count,seen_events.get(fingerprint,0))
    return result


def parse_log(raw,zone,origin,identity=None):
    total_bytes=0;seen_events={};summaries=[];components=[]
    def walk(data,prefix='',depth=0):
        nonlocal total_bytes
        if depth>4:raise ValueError('nested log depth exceeds four')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)):raise ValueError('duplicated nested log members')
            if 'logd.dat' not in names:raise ValueError('unexpected nested log members')
            if any(n!='logd.dat' and not n.endswith('.jez') for n in names):raise ValueError('unexpected nested log members')
            for name in sorted(n for n in names if n!='logd.dat'):
                if archive.getinfo(name).file_size>MAX_LOG_BYTES:raise ValueError('nested log exceeds bound')
                walk(archive.read(name),prefix+name+'/',depth+1)
            size=archive.getinfo('logd.dat').file_size;total_bytes+=size
            if total_bytes>MAX_LOG_BYTES:raise ValueError('log history exceeds explicit 128 MiB bound')
            leaf_hash=hashlib.sha256()
            with archive.open('logd.dat') as stream:
                def lines():
                    for rawline in stream:
                        leaf_hash.update(rawline)
                        yield rawline.decode('latin1')
                summaries.append(summarize_log_lines(lines(),zone,origin,identity=identity,seen_events=seen_events))
            components.append({'member':prefix+'logd.dat','bytes':size,'sha256':leaf_hash.hexdigest()})
    walk(raw)
    result=dict(summaries[0])
    for part in summaries[1:]:
        for key,value in part.items():
            if key in ['log_status','log_contagem_temporal_confiavel']:continue
            if isinstance(value,int) and not isinstance(value,bool):result[key]=(result.get(key) or 0)+value
            elif key.endswith(('_original','_brasilia')) and value is not None:result[key]=max(value,result.get(key) or value)
    active=[p for p in summaries if any(p.get(k) for k in ['log_total_computados','log_total_confirmados_presidente','log_eventos_sem_turno','log_eventos_sem_identidade'])]
    result['log_contagem_temporal_confiavel']=bool(active) and all(p['log_contagem_temporal_confiavel'] for p in active)
    result['log_componentes_json']=json.dumps(components,separators=(',',':'))
    return result


def _signature_hash(algorithm,data):
    names={1:'sha1',2:'sha256',3:'sha384',4:'sha512'}
    if algorithm not in names:raise ValueError('unknown hash algorithm')
    return hashlib.new(names[algorithm],data).digest()


def verify_signatures(raw,read_member,has_member,*,verify_crypto=True):
    """Verify published bytes; distinguish unsupported SW from HW signatures.

    Trust check uses the issuer public keys embedded in the unmodified official
    helper. This is explicitly not a complete RFC5280/revocation validation.
    """
    codec=signature_codec();obj=decode_complete(codec,'EntidadeAssinaturaEcourna',raw)
    result={'assinatura_status':'ok','assinatura_modelo':obj['origemAssinaturaHW']['modeloEquipamento'],
            'assinatura_hw_algoritmo':obj['origemAssinaturaHW']['algoritmoAssinatura'],
            'assinatura_hashes_verificados':0,'assinatura_hashes_incompativeis':0,
            'assinatura_membros_nao_publicados':0,'assinatura_hw_verificadas':0,'assinatura_hw_invalidas':0,
            'assinatura_hw_autoassinatura':'nao_verificada','assinatura_certificado':'nao_verificado',
            'assinatura_cadeia':'nao_verificada','assinatura_sw':'algoritmo_cepesc_nao_verificado',
            'assinatura_erros_json':'[]','assinatura_itens_json':'[]'}
    hw=None;verifier=None;errors=[]
    if verify_crypto:
        try:
            from .official import mr_util as official
            from base64 import b64decode
            s=obj['assinaturaHW']
            if s['informacaoChave'][0]!='certificadoDigital':
                result['assinatura_certificado']='chave_por_tag_sem_certificado'
            else:
                cert=official.converte_certificado_para_x509(s['informacaoChave'][1],official._modelo(result['assinatura_modelo']))
                decoded=official.decode_x509(cert)
                # The official helper expects DER; preserve its exact path for PEM/DER.
                decoded,_,hw,verifier=official.extrai_chave_do_certificado(decoded)
                result['assinatura_certificado']='chave_extraida'
                validity=decoded['tbsCertificate']['validity']
                def cert_date(value):
                    kind,stamp=value
                    if isinstance(stamp,datetime):return stamp
                    return datetime.strptime(stamp, '%y%m%d%H%M%SZ' if kind=='utcTime' else '%Y%m%d%H%M%SZ')
                try:
                    election_date=datetime(2026,10,25,20,0,0)
                    result['assinatura_validade_eleicao']=cert_date(validity['notBefore'])<=election_date<=cert_date(validity['notAfter'])
                except (ValueError,TypeError,KeyError):result['assinatura_validade_eleicao']=None
                try:
                    trusted=official.valida_certificado(decoded,verifier)
                    result['assinatura_cadeia']='emissor_oficial_assinatura_compativel' if trusted else 'assinatura_emissor_invalida'
                except (ValueError,RuntimeError,KeyError,TypeError) as e:
                    result['assinatura_cadeia']='emissor_nao_validado';errors.append('issuer:'+type(e).__name__)
                result['assinatura_certificado_sha256']=hashlib.sha256(s['informacaoChave'][1]).hexdigest()
        except Exception as e:
            result['assinatura_certificado']='nao_suportado_ou_erro';errors.append('certificate:'+type(e).__name__)
    items=[]
    for group in ['assinaturaSW','assinaturaHW']:
        s=obj[group];algo=s['autoAssinado']['algoritmoHash']['algoritmo'];payload=s['conteudoAutoAssinado']
        container_hash=_signature_hash(algo,payload)
        if container_hash!=s['autoAssinado']['assinatura']['hash']:
            result['assinatura_hashes_incompativeis']+=1;errors.append(group+':container_hash')
        if group=='assinaturaHW' and hw is not None:
            try:
                ok=bool(verifier.verify(hashlib.sha512(container_hash).digest(),s['autoAssinado']['assinatura']['assinatura'],hw))
                result['assinatura_hw_autoassinatura']='compativel' if ok else 'invalida'
            except Exception as e:
                errors.append('auto_signature:'+type(e).__name__);result['assinatura_hw_autoassinatura']='erro'
        signed=decode_complete(codec,'Assinatura',payload)
        for entry in signed['arquivosAssinados']:
            name=entry['nomeArquivo']
            if not has_member(name):
                result['assinatura_membros_nao_publicados']+=1
                continue
            data=read_member(name)
            actual=_signature_hash(algo,data);match=actual==entry['assinatura']['hash']
            result['assinatura_hashes_verificados']+=1
            if not match:result['assinatura_hashes_incompativeis']+=1
            signature_status='nao_verificada'
            if group=='assinaturaHW' and hw is not None:
                try:
                    ok=bool(verifier.verify(hashlib.sha512(entry['assinatura']['hash']).digest(),entry['assinatura']['assinatura'],hw))
                    result['assinatura_hw_verificadas']+=1
                    result['assinatura_hw_invalidas']+=int(not ok)
                    signature_status='compativel' if ok else 'invalida'
                except Exception as e:
                    signature_status='erro';errors.append('member_signature:'+type(e).__name__)
            items.append({'grupo':group,'nome':name,'sha256':hashlib.sha256(data).hexdigest(),'hash_compativel':match,'assinatura':signature_status})
    result['assinatura_itens_json']=json.dumps(items,separators=(',',':'))
    result['assinatura_erros_json']=json.dumps(errors)
    if result['assinatura_hashes_incompativeis'] or result['assinatura_hw_invalidas'] or result['assinatura_hw_autoassinatura']=='invalida':result['assinatura_status']='divergencia'
    elif errors or (verify_crypto and (hw is None or result['assinatura_cadeia']!='emissor_oficial_assinatura_compativel' or result.get('assinatura_validade_eleicao') is not True)):result['assinatura_status']='verificacao_parcial'
    return result
