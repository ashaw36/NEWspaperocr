#!/usr/bin/env python
"""快速功能验证脚本 - 测试新增模块"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))


def test_document_composer():
    """测试文档生成器"""
    print("测试: DocumentComposer")
    print("-" * 50)

    from document_composer import DocumentComposer

    # Mock data
    task_data = {
        'filename': '测试报纸.png',
        'id': 'test-001'
    }

    pages = [{
        'page_number': 1,
        'regions': [
            {
                'article_id': 'article-1',
                'label': 'title',
                'corrected_text': '测试标题',
                'confidence': 0.98
            },
            {
                'article_id': 'article-1',
                'label': 'body',
                'corrected_text': '这是第一篇文章的正文内容。',
                'confidence': 0.96
            },
            {
                'article_id': 'article-2',
                'label': 'body',
                'corrected_text': '这是第二篇文章的内容。',
                'confidence': 0.95
            }
        ]
    }]

    composer = DocumentComposer()

    # Test Markdown generation
    markdown = composer.compose_markdown(task_data, pages)
    assert '测试报纸' in markdown
    assert '测试标题' in markdown
    assert '识别质量报告' in markdown
    print("✅ Markdown 生成正常")

    # Test HTML generation
    html = composer.compose_html(task_data, pages)
    assert 'DOCTYPE html' in html
    assert '测试标题' in html
    assert 'article-title' in html
    print("✅ HTML 生成正常")

    # Test article extraction
    articles = composer._extract_articles(pages)
    assert len(articles) == 2
    assert articles[0]['title'] == '测试标题'
    print(f"✅ 文章提取正常: {len(articles)}篇")

    # Test quality calculation
    metrics = composer._calculate_quality(pages)
    assert metrics['total_regions'] == 3
    assert metrics['avg_confidence'] > 0.9
    print(f"✅ 质量指标计算正常: 平均置信度 {metrics['avg_confidence']:.1%}")

    print()


def test_quality_validator():
    """测试质量验证器"""
    print("测试: QualityValidator")
    print("-" * 50)

    from quality_validator import QualityValidator

    # Mock task data
    task_data = {
        'id': 'test-001',
        'pages': [{
            'page_number': 1,
            'layout': {'source': 'ai+computer-vision'},
            'regions': [
                {
                    'region_id': 'r1',
                    'label': 'title',
                    'article_id': 'a1',
                    'corrected_text': '标题内容',
                    'confidence': 0.98
                },
                {
                    'region_id': 'r2',
                    'label': 'body',
                    'article_id': 'a1',
                    'corrected_text': '正文内容' * 100,
                    'confidence': 0.96
                },
                {
                    'region_id': 'r3',
                    'label': 'body',
                    'article_id': 'a2',
                    'corrected_text': '另一篇文章',
                    'confidence': 0.95
                }
            ]
        }]
    }

    validator = QualityValidator(target_accuracy=0.95)

    # Run validation
    report = validator.validate_task(task_data)

    # Check structure
    assert 'passed' in report
    assert 'completeness' in report
    assert 'accuracy' in report
    assert 'layout_quality' in report
    assert 'article_quality' in report
    assert 'recommendations' in report

    print(f"✅ 验证通过: {report['passed']}")
    print(f"✅ 完整性: {report['completeness']['score']:.1%}")
    print(f"✅ 准确率: {report['accuracy']['score']:.1%}")
    print(f"✅ 版面质量: {report['layout_quality']['score']:.1%}")
    print(f"✅ 识别文章: {report['article_quality']['total_articles']}篇")

    # Test individual checks
    completeness = validator._check_completeness(task_data['pages'])
    assert completeness['score'] == 1.0
    print(f"✅ 完整性检查: {completeness['score']:.1%}")

    accuracy = validator._estimate_accuracy(task_data['pages'])
    assert accuracy['score'] > 0.9
    print(f"✅ 准确率估算: {accuracy['score']:.1%}")

    layout = validator._check_layout_quality(task_data['pages'])
    assert layout['score'] == 1.0
    print(f"✅ 版面质量检查: {layout['score']:.1%}")

    articles = validator._check_article_aggregation(task_data['pages'])
    assert articles['total_articles'] == 2
    print(f"✅ 文章聚合检查: {articles['total_articles']}篇")

    print()


def test_workflow_integration():
    """测试工作流集成"""
    print("测试: Workflow 集成")
    print("-" * 50)

    import workflow

    # Check new methods exist
    workflow_instance = workflow.Workflow()

    assert hasattr(workflow_instance, 'generate_final_document')
    print("✅ generate_final_document() 方法存在")

    assert hasattr(workflow_instance, 'validate_quality')
    print("✅ validate_quality() 方法存在")

    print()


def test_api_endpoints():
    """测试API端点"""
    print("测试: API 端点")
    print("-" * 50)

    try:
        import requests

        # Check if service is running
        response = requests.get("http://127.0.0.1:5000/api/health", timeout=3)
        if response.status_code == 200:
            print("✅ API 服务运行中")

            health = response.json()
            print(f"   OCR: {health['ocr']['backend']}")
            print(f"   AI: {health['ai']['backend']}")
        else:
            print("⚠️  API 服务未运行（需要手动启动）")

    except requests.exceptions.ConnectionError:
        print("⚠️  API 服务未运行（需要手动启动）")
    except ImportError:
        print("⚠️  requests 未安装，跳过 API 测试")

    print()


def main():
    print("=" * 50)
    print("古报纸 OCR - 功能验证")
    print("=" * 50)
    print()

    tests = [
        ("文档生成器", test_document_composer),
        ("质量验证器", test_quality_validator),
        ("工作流集成", test_workflow_integration),
        ("API端点", test_api_endpoints),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ 测试失败: {name}")
            print(f"   错误: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            print()

    print("=" * 50)
    print(f"测试完成: {passed} 通过, {failed} 失败")
    print("=" * 50)

    if failed == 0:
        print("\n✅ 所有核心功能正常!")
        print("\n下一步:")
        print("1. 启动服务: python app.py")
        print("2. 访问演示: http://127.0.0.1:5000/demo.html")
        print("3. 运行验收测试: python acceptance_test.py <图片路径>")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
