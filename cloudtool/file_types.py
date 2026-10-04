"""Content signatures shared by capture and upload preflight."""
def binary_type(data):
    for signature,mime,extension in (
        (b'GIF87a','image/gif','.gif'),(b'GIF89a','image/gif','.gif'),
        (b'\x89PNG\r\n\x1a\n','image/png','.png'),(b'\xff\xd8\xff','image/jpeg','.jpg'),
        (b'%PDF-','application/pdf','.pdf'),(b'PK\x03\x04','application/zip','.zip'),
        (b'wOFF','font/woff','.woff'),(b'wOF2','font/woff2','.woff2')):
        if data.startswith(signature):return mime,extension
    if data.startswith(b'RIFF') and data[8:12]==b'WEBP':return 'image/webp','.webp'
    return None
