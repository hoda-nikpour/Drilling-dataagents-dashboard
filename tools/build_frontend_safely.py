"""Publish a successful frontend build without deleting assets in active use."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
FRONTEND=ROOT/'streamlit_components/virtual_log_viewer/frontend'


def main():
    with tempfile.TemporaryDirectory(prefix='.audit-build-',dir=FRONTEND) as temporary:
        subprocess.run(['npm','run','build','--','--outDir',temporary,'--emptyOutDir'],cwd=FRONTEND,check=True)
        staging=Path(temporary);target=FRONTEND/'dist'
        shutil.copytree(staging/'assets',target/'assets',dirs_exist_ok=True)
        next_index=target/'.index-next.html'
        shutil.copy2(staging/'index.html',next_index)
        os.replace(next_index,target/'index.html')
    print('Published the new index; existing assets remain available to open sessions.')


if __name__=='__main__':main()
