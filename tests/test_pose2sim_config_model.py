import unittest

from app.pose2sim.config_model import ConfigModel


CONFIG_TEXT = '''# 配置标题
[project]
frame_rate = 'auto' # fps
multi_person = false
participant_mass = 70.0
frame_range = [0, 120]

[pose]
pose_model = 'Body_with_feet'
det_frequency = 4 # 每隔若干帧检测人物
mode = """{'pose_class':'RTMPose',
'pose_input_size':[192,256]}"""

[[pose.CUSTOM]]
name = "Hip"
id = 0

[synchronization]
synchronization_gui = true
'''


class Pose2SimConfigModelTests(unittest.TestCase):
    def test_parse_exposes_scalar_types_and_marks_complex_values_read_only(self) -> None:
        model = ConfigModel.parse(CONFIG_TEXT)
        parameters = {parameter.path: parameter for parameter in model.parameters}

        self.assertEqual(parameters[("project", "multi_person")].value_type, "bool")
        self.assertEqual(parameters[("pose", "det_frequency")].value_type, "int")
        self.assertEqual(parameters[("project", "participant_mass")].value_type, "float")
        self.assertEqual(parameters[("project", "frame_rate")].value_type, "string")
        self.assertEqual(parameters[("project", "frame_range")].value_type, "list")
        self.assertFalse(parameters[("pose", "mode")].editable)
        self.assertFalse(parameters[("pose", "CUSTOM")].editable)

    def test_set_value_preserves_comments_order_unknown_fields_and_array_tables(self) -> None:
        model = ConfigModel.parse(CONFIG_TEXT)

        text = model.set_value(("pose", "det_frequency"), "2")

        self.assertIn("# 配置标题", text)
        self.assertIn("det_frequency = 2 # 每隔若干帧检测人物", text)
        self.assertLess(text.index("[project]"), text.index("[pose]"))
        self.assertLess(text.index("[pose]"), text.index("[synchronization]"))
        self.assertIn("[[pose.CUSTOM]]", text)
        self.assertIn("name = \"Hip\"", text)

    def test_add_and_remove_parameter_preserve_neighboring_content(self) -> None:
        model = ConfigModel.parse(CONFIG_TEXT)

        added = model.add_parameter(("filtering",), "filter", "true")
        self.assertIn("[filtering]", added)
        self.assertIn("filter = true", added)
        self.assertIn("[[pose.CUSTOM]]", added)

        removed = ConfigModel.parse(added).remove_parameter(("filtering", "filter"))
        self.assertNotIn("filter = true", removed)
        self.assertIn("[filtering]", removed)
        self.assertIn("[synchronization]", removed)

    def test_invalid_value_duplicate_key_and_missing_remove_do_not_mutate_model(self) -> None:
        model = ConfigModel.parse(CONFIG_TEXT)
        original = model.as_text()

        with self.assertRaises(ValueError):
            model.set_value(("pose", "det_frequency"), "[invalid")
        with self.assertRaises(ValueError):
            model.add_parameter(("pose",), "det_frequency", "8")
        with self.assertRaises(KeyError):
            model.remove_parameter(("pose", "missing"))

        self.assertEqual(model.as_text(), original)


if __name__ == "__main__":
    unittest.main()
