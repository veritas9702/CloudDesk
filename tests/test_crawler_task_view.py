import unittest
from cloudtool.crawler.task_view import ordered, summary

class TaskViewTests(unittest.TestCase):
    def test_status_and_completion_order(self):
        states = ['已完成', '部分完成', '采集失败', '已暂停', '采集中', '等待', '已完成']
        rows = [dict(id=str(i), state=state, ended_at=f'2026-10-03T00:00:0{i}+00:00') for i,state in enumerate(states)]
        self.assertEqual([r['id'] for r in ordered(rows)], ['5','4','3','2','1','6','0'])
        counts = summary(rows)
        self.assertEqual(counts['total'], sum(v for k,v in counts.items() if k != 'total'))
        self.assertEqual(counts['completed'], 2)
