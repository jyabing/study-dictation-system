# Study App 结构说明

## views/
- book_views.py      书册首页 / 详情
- lesson_views.py    lesson 页面
- train_views.py     训练入口页面

## services/
- scheduler.py       出题调度（艾宾浩斯）
- grader.py          判题逻辑

## templates/study/
- dashboard.html     首页
- book_detail.html   书册详情
- train.html         训练页面

## static/js/
- train.js           前端训练逻辑

## api/
- train_api.py       出题 & 提交答案接口