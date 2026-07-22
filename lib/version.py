"""
版本號單一來源（single source of truth）。

所有需要顯示版本的地方都從這裡 import，不要各自寫死：
  from lib.version import __version__

進版時只改這裡一處，並同步：
  1. README 第 9 節版本記錄補一列
  2. git tag 打 v{__version__}
"""
__version__ = "1.2.4"
