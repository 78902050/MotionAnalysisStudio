# Real-format test fixtures

These fixtures preserve the field layout of data under `D:\test\data` while keeping the repository sample small.

- `calibration/camera_array.toml`: four-camera Caliscope TOML from the `8.12` sample.
- `calibration/camera_array_aniposelib.toml`: the corresponding aniposelib TOML.
- `calibration/camera_array_empty.toml`: a real empty `[cameras]` export from the `8.18` sample.
- `pose/cam01_json/cam01_000000.json` and `pose/cam02_json/cam02_000000.json`: one OpenPose-style Pose2Sim frame from two cameras in the `8.12/走路` trial.

The files contain calibration values and pose coordinates only. Original videos are not copied or modified. A trimmed TRC fixture is intentionally deferred until its declared frame counts can be updated together with the retained rows.
