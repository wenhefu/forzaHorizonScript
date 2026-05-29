from __future__ import annotations

import argparse
from pathlib import Path


def export_bootstrap_model(output: str | Path = "v3/models/bootstrap_empty.onnx") -> Path:
    try:
        import numpy as np
        import onnx
        from onnx import TensorProto, helper, numpy_helper
    except Exception as exc:
        raise RuntimeError(
            "The bootstrap exporter needs the 'onnx' package. "
            "Install it with: .\\.venv\\Scripts\\python.exe -m pip install onnx"
        ) from exc

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    input_tensor = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])
    output_tensor = helper.make_tensor_value_info("detections", TensorProto.FLOAT, [1, 1, 6])
    const = numpy_helper.from_array(np.zeros((1, 1, 6), dtype=np.float32), name="empty_detections")
    node = helper.make_node("Constant", inputs=[], outputs=["detections"], value=const)
    graph = helper.make_graph([node], "forza_ui_empty_detector", [input_tensor], [output_tensor])
    model = helper.make_model(graph, producer_name="forza6helper-v3-bootstrap", opset_imports=[helper.make_opsetid("", 12)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a valid empty ONNX detector for packaging/runtime tests.")
    parser.add_argument("--output", default="v3/models/bootstrap_empty.onnx")
    args = parser.parse_args(argv)
    path = export_bootstrap_model(args.output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
