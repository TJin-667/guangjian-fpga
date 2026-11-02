"""Export measured device service counters; no cross-domain subtraction/sum."""
import html,json
from pathlib import Path
from archive0109 import read,verify_profiles

def export(x,out):
    source=read(x['root']/'RESULT.json');rows=verify_profiles(source)
    record=dict(schema='guangjian-0109-device-service-v1',group_id=x['group_id'],physical_hardware=x['physical_hardware'],rows=rows,
        pure_arithmetic_cycles=None,FPGA_speedup=None,
        caveat='Inclusive service cycles in each local domain. Scratch descriptor is accepted at ARM and can include waiting for capture/H2 arrival. H2 and scratch overlap; never sum domains or infer arithmetic-only cycles from unblocked cycles. Software peer counters are test models.')
    Path(out/'DEVICE_SERVICE.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    table=['<tr><th>帧</th><th>阶段</th><th>本域MHz</th><th>服务周期</th><th>毫秒</th><th>事件0</th><th>事件1</th><th>观察到的阻塞周期</th></tr>']
    for p in rows:
        stage=('H2（含DDR读取）','scratch写入','融合（含DDR访问）')[p['stage']]
        table.append(f"<tr><td>{p['slot']}</td><td>{stage}</td><td>{p['clock_hz']/1e6:g}</td><td>{p['service_cycles']}</td><td>{p['service_seconds']*1000:.4f}</td><td title='{html.escape(p['count0_meaning'])}'>{p['count0']}</td><td title='{html.escape(p['count1_meaning'])}'>{p['count1']}</td><td>{p['blocked_cycles']}</td></tr>")
    title='器件本域服务计数' if x['physical_hardware'] else '软件模拟计数：不能作为FPGA性能'
    content='<!doctype html><meta charset="utf-8"><title>光鉴0109分段计数</title><style>body{font:16px Microsoft YaHei;max-width:1200px;margin:30px auto}table{border-collapse:collapse}td,th{border:1px solid #bccbd8;padding:7px}</style><h1>'+title+'</h1><p>包含存储、CDC及背压等待；不是纯算术时间。scratch还可能包含ARM后等待采集/H2到达。H2和scratch存在重叠，不可跨域相加或相减。加速比待同输入、同边界的PC／FPGA比较。</p><table>'+''.join(table)+'</table>'
    (out/'DEVICE_SERVICE.html').write_text(content,encoding='utf-8')
    return record
