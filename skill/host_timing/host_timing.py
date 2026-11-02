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
