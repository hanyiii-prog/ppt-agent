from ppt_agent.story import architect_markdown_to_ir, architect_story, story_to_ir

MD = """# 口腔医院项目汇报
## 封面
- 汇报人：韩熠
## 项目进展
- 完成互联互通上线
- 通过测评
## 总结
- 下一步推广
"""


def test_architect_story_structure():
    story = architect_story(MD, audience="院方", objective="汇报上线成果")
    assert story.title == "口腔医院项目汇报"
    assert story.audience == "院方"
    assert story.slides[0].purpose == "cover"
    assert story.slides[-1].purpose == "closing"
    content = [slide for slide in story.slides if slide.purpose == "content"][0]
    assert "完成互联互通上线" in content.points


def test_story_to_ir_produces_slides_and_components():
    story = architect_story(MD)
    ir = story_to_ir(story)
    assert len(ir.slides) == len(story.slides)
    assert ir.title == "口腔医院项目汇报"
    assert ir.slides[1].components[0].type == "title"
    assert ir.slides[1].components[0].text == "项目进展"


def test_architect_story_title_only_falls_back_to_cover():
    story = architect_story("# Only Title")
    assert len(story.slides) == 1
    assert story.slides[0].purpose == "cover"


def test_architect_markdown_to_ir_helper():
    ir = architect_markdown_to_ir(MD, objective="demo")
    assert ir.objective == "demo"
    assert len(ir.slides) == 3
