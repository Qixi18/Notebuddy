"""Render pages only: semantic interpretation belongs to the configured model."""
from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from app.core.config import settings


def office_converter() -> str | None:
    if os.getenv('NOTEBOOK_GOTENBERG_URL'):
        return 'gotenberg'
    configured = os.getenv('NOTEBOOK_SOFFICE_PATH')
    for candidate in [configured, shutil.which('soffice'),
                      r'C:\Program Files\LibreOffice\program\soffice.exe']:
        if candidate and Path(candidate).is_file():
            return candidate
    if os.name == 'nt':
        return 'windows-office'
    return None


def convert_office(path: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'{path.stem}.pdf'
    if target.is_file():
        return target
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    converter = office_converter()
    owner_record = output / 'office-process.json'
    try:
        if converter == 'gotenberg':
            import httpx
            endpoint = os.environ['NOTEBOOK_GOTENBERG_URL'].rstrip('/')
            temporary = target.with_suffix('.tmp')
            try:
                with (path.open('rb') as source, httpx.Client(timeout=120) as client,
                      client.stream('POST', f'{endpoint}/forms/libreoffice/convert',
                                    files={'files': (path.name, source)}) as response):
                    response.raise_for_status()
                    with temporary.open('wb') as output_file:
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > settings.llm_max_upload_bytes:
                                raise RuntimeError('转换后的 PDF 超出全程 AI 文件上限')
                            output_file.write(chunk)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        elif converter == 'windows-office':
            helper = Path(__file__).with_name('render_office.ps1')
            owner_record.unlink(missing_ok=True)
            subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(helper),
                            '-Source', str(path.resolve()), '-Target', str(target.resolve()),
                            '-OwnerProcessFile', str(owner_record.resolve())],
                           check=True, timeout=120, capture_output=True, **flags)
        elif converter:
            profile = (output / 'lo-profile').resolve().as_uri()
            subprocess.run([converter, f'-env:UserInstallation={profile}', '--headless',
                            '--convert-to', 'pdf', '--outdir', str(output), str(path)],
                           check=True, timeout=120, capture_output=True, **flags)
        else:
            raise RuntimeError('Office 转页不可用：请安装 Word/PowerPoint 或配置 LibreOffice')
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError('Office 转页未产生有效 PDF，请检查文件或转换器')
        return target
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError('Office 转页失败或超时，请检查本机 Office/LibreOffice 后重试') from exc
    finally:
        if converter == 'windows-office':
            try:
                helper = Path(__file__).with_name('cleanup_office.ps1')
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                    '-File', str(helper), '-OwnerProcessFile', str(owner_record.resolve())],
                    timeout=10, check=False, capture_output=True, **flags)
                if result.returncode == 0:
                    owner_record.unlink(missing_ok=True)
            except (OSError, subprocess.TimeoutExpired):
                pass  # Retain the ownership record for diagnosis; never kill an unverified PID.


@contextmanager
def page_images(path: Path, asset_id: str, max_pages: int):
    """Yield (page_count, render(page_number)); only one raster is held at a time."""
    if path.suffix.lower() in {'.pptx', '.docx'}:
        path = convert_office(path, settings.derived_dir / 'converted' / asset_id)
    if path.suffix.lower() == '.pdf':
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(str(path))
        try:
            count = len(document)
            if not 0 < count <= max_pages:
                raise RuntimeError(f'页面数超出全程 AI 路线限制（最多 {max_pages} 页）')
            def render(number):
                page = document[number - 1]
                try:
                    width, height = page.get_size()
                    scale = min(2.0, 2400 / max(width, height, 1))
                    bitmap = page.render(scale=scale)
                    try:
                        with bitmap.to_pil() as image:
                            buffer = BytesIO()
                            image.save(buffer, format='PNG')
                            return buffer.getvalue()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            yield count, render
        finally:
            document.close()
    else:
        from PIL import Image
        def render(number):
            with Image.open(path) as original, original.convert('RGB') as image:
                image.thumbnail((2400, 2400))
                buffer = BytesIO()
                image.save(buffer, format='PNG')
                return buffer.getvalue()
        yield 1, render
