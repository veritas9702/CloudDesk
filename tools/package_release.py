"""Package only the current source and app; never include machine-local data."""
import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ('main.py','README.md','requirements.txt','requirements-dev.txt','requirements-build.txt','start.bat','setup.bat','build.bat','cleanup.bat','CloudDesk.spec','.gitignore')
FOLDERS = ('app/releases/0.16.24','cloudtool','browser_extension','docs','tests','tools','examples','THIRD_PARTY_LICENSES')
FORBIDDEN = {'pending-input.json','pending-input.tmp','profiles.json','cookies','login data','history','browser-authorization','.venv','.git','__pycache__','.local-browsers','.clouddesk-capture-work','WebsiteTemplates'.lower()}

def package(destination):
    if not (ROOT/'app/releases/0.16.24/CloudDesk/CloudDesk.exe').is_file():
        raise SystemExit('Run build.bat first.')
    destination=Path(destination).resolve()
    if destination==ROOT or any(destination.is_relative_to(ROOT/folder) for folder in FOLDERS):
        raise ValueError('Output must be outside packaged source/app folders')
    destination.mkdir(parents=True,exist_ok=True)
    archive=destination/'CloudDesk-Windows.zip'
    paths=[ROOT/name for name in FILES]
    for folder in FOLDERS:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and not FORBIDDEN.intersection(part.lower() for part in p.relative_to(ROOT).parts))
    for path in paths:
        if path.suffix.lower() in ('.db','.sqlite','.sqlite3','.pyc') or path.name.lower().endswith(('.sqlite3-wal','.sqlite3-shm','.db-wal','.db-shm')):raise ValueError('Unexpected data file in package inputs')
        if path.is_symlink():raise ValueError('Links are not packaged')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in paths:bundle.write(path,'CloudDesk/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:raise ValueError('Archive validation failed')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination/'SHA256.txt').write_text(f'{digest}  {archive.name}\n','utf-8')
    print(f'{archive}\n{archive.stat().st_size/1048576:.1f} MB')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    package(parser.parse_args().output)
