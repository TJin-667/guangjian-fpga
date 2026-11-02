"""Immutable, validated per-run identity and exposure settings; no board IO."""
import re
from dataclasses import dataclass,asdict

MIN_LINES=1
MAX_LINES=1116  # Exact current0107 TransportExecutor.acquire validation bound.

@dataclass(frozen=True)
class CaptureSettings:
    specimen: str
    variant: str='A_v1'
    low: int=400
    high: int=800
    def __post_init__(self):
        name=self.specimen
        if not isinstance(name,str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',name) is None:
            raise ValueError('样品名请输入1～64个英文字母、数字、下划线或短横线，首字符须为字母或数字；与现有采集身份协议保持一致。')
        reserved={'CON','PRN','AUX','NUL'}|{prefix+str(i) for prefix in ('COM','LPT') for i in range(1,10)}
        if name.upper() in reserved:raise ValueError('该样品名是Windows保留名称，请更换。')
        if not isinstance(self.variant,str) or re.fullmatch(r'[AB]_v[0-9]{1,3}',self.variant) is None:
            raise ValueError('面/阶段请使用A_v0、A_v1、B_v0或B_v1等格式。')
        if any(type(v) is not int or not MIN_LINES<=v<=MAX_LINES for v in (self.low,self.high)):
            raise ValueError('低、高曝光均须为1～1116行的整数（现用0107模式范围）。')
        if self.low>=self.high:raise ValueError('低曝光必须小于高曝光；不能相同或颠倒。')
    @classmethod
    def from_text(cls,specimen,variant,low,high):
        try:lo=int(low);hi=int(high)
        except (ValueError,TypeError):raise ValueError('低、高曝光请输入整数行数。') from None
        if isinstance(low,bool) or isinstance(high,bool) or any(isinstance(v,float) for v in (low,high)):
            raise ValueError('低、高曝光请输入整数行数。')
        return cls(str(specimen).strip(),str(variant).strip(),lo,hi)
    @property
    def preview_lines(self):return (self.low+self.high)//2
    def document(self):return dict(schema='per-run-capture-settings-v1',**asdict(self),preview_lines=self.preview_lines,
        gain16=16,LED=128,exposure_unit='sensor_lines',settings_frozen_at_start=True)

def for_runtime(runtime):
    value=getattr(runtime,'capture_settings',None)
    if value is None:value=CaptureSettings(runtime.specimen,runtime.variant)
    if value.specimen!=runtime.specimen or value.variant!=runtime.variant:
        raise ValueError('冻结设置与当前样品身份不符，停止本轮。')
    return value
