import tempfile
import unittest
from pathlib import Path
from cloudtool.crawler.paths import original_path, unique_path
from cloudtool.crawler.document import html_document
from cloudtool.crawler.repository import Repository
from cloudtool.crawler.models import Settings


class StructureTests(unittest.TestCase):
    def test_original_paths_and_safe_exceptions(self):
        seed = 'https://site.test/'
        self.assertEqual(original_path(seed + 'template/1/style.css', 'asset', seed), 'template/1/style.css')
        self.assertEqual(original_path(seed + 'news/a.html', 'page', seed), 'news/a.html')
        self.assertEqual(original_path(seed + 'zh/', 'page', seed), 'zh/index.html')
        self.assertEqual(original_path(seed + 'article.php', 'page', seed), 'article.php.html')
        self.assertNotEqual(original_path(seed+'a.html?id=1','page',seed), original_path(seed+'a.html?id=2','page',seed))
        self.assertEqual(original_path('https://cdn.test/x/logo.png','asset',seed), '_external/cdn.test/x/logo.png')
        for path in ('CON', '..', '%2F', 'name%3F.jpg'):
            result = original_path(seed + path, 'asset', seed)
            self.assertNotIn('..', Path(result).parts)
            self.assertNotEqual(result, path)
        self.assertNotEqual(unique_path('A.html',seed,{'a.html'},set()), 'A.html')
        self.assertNotEqual(unique_path('a/x.jpg',seed,{'a'},set()), 'a/x.jpg')

    def test_gbk_html_retains_encoding_and_page_elements(self):
        source = '<html><head><meta charset="gbk"><title>中文标题</title></head><body><section class="hero"><img src="/图.png"></section><script>var a=1;</script></body></html>'.encode('gbk')
        data = html_document(source, 'https://site.test/', lambda v,*_:v, rewrite=True)
        text = data.decode('gbk')
        self.assertIn('中文标题', text)
        self.assertIn('charset="gbk"', text)
        self.assertIn('<section class="hero">', text)
        self.assertIn('var a=1;', text)

    def test_case_collision_and_legacy_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Repository(Path(temp)/'state')
            try:
                key=repo.create(['https://site.test/'],str(Path(temp)/'out'),Settings().validate())[0]
                for url in ('https://site.test/A.html','https://site.test/a.html'):
                    repo.add(key,url,'page',1,'https://site.test/')
                paths=[r['path'].casefold() for r in repo.rows(key)]
                self.assertEqual(len(paths),len(set(paths)))
                legacy=Settings().validate();legacy.pop('layout')
                key=repo.create(['https://old.test/'],str(Path(temp)/'old'),legacy)[0]
                repo.upgrade_settings(key,Settings().validate())
                repo.add(key,'https://old.test/a.png','asset',0,'https://old.test/')
                self.assertTrue(repo.rows(key)[1]['path'].startswith('assets/'))
            finally:
                repo.close()
