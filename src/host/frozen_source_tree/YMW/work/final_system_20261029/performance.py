"""Host wall-clock accounting. Nested spans are inclusive, never FPGA cycles."""
import contextlib,functools,hashlib,html,json,time
from pathlib import Path

class Ledger:
    def __init__(self,clock=time.perf_counter_ns):
        self.clock=clock;self.started=clock();self.events=[];self.aggregates={};self.costs=[]
    @contextlib.contextmanager
    def span(self,name,**details):
        start=self.clock();ok=False
        try:
            yield;ok=True
        finally:
            self.events.append(dict(name=name,seconds=max(0,self.clock()-start)/1e9,success=ok,inclusive=True,**details))
    def wrap(self,fn,name):
        @functools.wraps(fn)
        def measured(*args,**kwargs):
            with self.span(name):return fn(*args,**kwargs)
        return measured
    def rpc(self,op,elapsed_ns,success,sent,received):
        row=self.aggregates.setdefault(str(op),dict(calls=0,failed=0,wall_seconds=0.,logical_request_bytes=0,logical_response_bytes=0))
        row['calls']+=1;row['failed']+=not success;row['wall_seconds']+=max(0,elapsed_ns)/1e9;row['logical_request_bytes']+=sent;row['logical_response_bytes']+=received
    def capture_cost(self,label,cost):self.costs.append(dict(label=label,cost=dict(cost)))
    def snapshot(self,**extra):
        keys=('udp_sent_packets','udp_sent_bytes','udp_received_packets','udp_received_bytes','command_retries','capture_requests','saved_images')
        return dict(schema='guangjian-host-performance-v1',clock='perf_counter_ns',scope='host_wall_clock_inclusive',
                    elapsed_seconds=max(0,self.clock()-self.started)/1e9,events=self.events,rpc=self.aggregates,capture_costs=self.costs,
                    summed_wire_cost={k:sum(r['cost'].get(k,0) for r in self.costs) for k in keys},
                    FPGA_core_cycles=None,FPGA_core_speedup=None,nested_events_must_not_be_summed=True,**extra)
    def save(self,path,**extra):
        path=Path(path);path.write_text(json.dumps(self.snapshot(**extra),ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')

def profiled_executor(implementation,Base,ledger):
    """Wrap only a private executor instance/module; original files stay pinned."""
    if hasattr(implementation,'references') and not getattr(implementation,'_closure_profiled',False):
        original=implementation.references
        def references():
            from types import SimpleNamespace
            fusion,h2,quality,connect,decode=original()
            fusion_proxy=SimpleNamespace(fuse_two_stage=ledger.wrap(fusion.fuse_two_stage,'pc_audit_fusion'))
            return fusion_proxy,ledger.wrap(h2,'pc_audit_H2'),ledger.wrap(quality,'pc_quality'),connect,ledger.wrap(decode,'R32_decode_and_baseline_connect')
        implementation.references=references;implementation._closure_profiled=True
    class ProfiledExecutor(Base):
        def __init__(self,**kwargs):
            super().__init__(**kwargs)
            if hasattr(self,'extension'):
                # Extension service times include RPC and polling; not device cycles.
                for name in ('wait_scratch','upload_quality','fuse','fetch','release'):
                    setattr(self.extension,name,ledger.wrap(getattr(self.extension,name),'service_'+name))
        def _extension_transport(self,request,sequence,timeout):
            started=ledger.clock();reply=None
            try:
                reply=super()._extension_transport(request,sequence,timeout);return reply
            finally:ledger.rpc(request[5],ledger.clock()-started,reply is not None,len(request),0 if reply is None else len(reply))
        def acquire(self,**kwargs):
            with ledger.span('formal_frame',slot=getattr(self,'_off_slot',0)+1):result=super().acquire(**kwargs)
            if hasattr(self,'_cost_record'):ledger.capture_cost('formal_'+str(getattr(self,'_off_slot',0)),self._cost_record())
            return result
        def acquire_roi_preparation(self,**kwargs):
            with ledger.span('ROI_preparation_not_formal'):result=super().acquire_roi_preparation(**kwargs)
            if hasattr(self,'_cost_record'):ledger.capture_cost('ROI_preparation',self._cost_record())
            return result
        def lights_off(self,*args,**kwargs):
            with ledger.span('cleanup_OFF'):result=super().lights_off(*args,**kwargs)
            if isinstance(result,dict) and 'cost' in result:ledger.capture_cost('cleanup_OFF',result['cost'])
            return result
    return ProfiledExecutor

def render_report(json_path):
    """A local evidence page; inclusive times are deliberately not added up."""
    path=Path(json_path);r=json.loads(path.read_text('utf-8'));rows=[]
    def group(title,record):
        rows.append('<h2>'+html.escape(title)+'</h2><table><tr><th>阶段（包含内部步骤）</th><th>秒</th><th>成功</th></tr>')
        for e in record.get('events',[]):rows.append('<tr><td>'+html.escape(e['name'])+'</td><td>'+f"{e['seconds']:.4f}"+'</td><td>'+str(e['success'])+'</td></tr>')
        rows.append('</table>')
        if record.get('rpc'):
            rows.append('<h3>扩展协议服务调用（含重试/等待，非器件周期）</h3><table><tr><th>op</th><th>次数</th><th>累计秒</th></tr>')
            for op,e in record['rpc'].items():rows.append(f'<tr><td>{html.escape(op)}</td><td>{e["calls"]}</td><td>{e["wall_seconds"]:.4f}</td></tr>')
            rows.append('</table>')
        if record.get('summed_wire_cost'):rows.append('<p>SDK实际UDP计数：'+html.escape(json.dumps(record['summed_wire_cost'],ensure_ascii=False))+'</p>')
    group('本次上位机处理',r)
    cp=r.get('source_capture_profile')
    if cp:
        raw=Path(cp).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=r.get('source_capture_profile_sha256'):raise ValueError('Capture performance evidence changed')
        group('同一组采集阶段',json.loads(raw))
    end=path.parent/'END_TO_END.json'
    if end.is_file():rows.append('<h2>完整任务区间</h2><pre>'+html.escape(end.read_text('utf-8'))+'</pre>')
    content='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>光鉴性能分段</title><style>body{font:16px "Microsoft YaHei",sans-serif;max-width:1100px;margin:30px auto;color:#20334b}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ccd6e3;text-align:left}pre{white-space:pre-wrap}h2{margin-top:28px}</style><h1>光鉴：性能分段记录</h1><p>这是主机墙钟时间。嵌套阶段包含内部工作，不得简单累加；RPC包含网络往返，不是FPGA纯计算周期。没有据此生成硬件加速比。</p>'''+''.join(rows)+'</html>'
    target=path.with_suffix('.html');target.write_text(content,'utf-8');return target
