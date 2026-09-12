# Build with: pyinstaller packaging.spec
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('backend')
a = Analysis(['run.py'], pathex=['.'], hiddenimports=hiddenimports, datas=[('frontend', 'frontend')],)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='github-repo-analyzer', console=True)
