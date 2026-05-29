from __future__ import annotations

import argparse
from pathlib import Path
import shutil


def export_checkpoint(
    checkpoint: str | Path,
    imgsz: int = 640,
    output: str | Path = "v3/models/forza_ui_yolo.onnx",
) -> Path:
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError(
            "Ultralytics is not installed. Install the training stack with:\n"
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements_vision.txt"
        ) from exc
    checkpoint = Path(checkpoint)
    if not checkpoint.exists():
        raise RuntimeError(f"checkpoint not found: {checkpoint}")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    exported = YOLO(str(checkpoint)).export(format="onnx", imgsz=imgsz, opset=12, simplify=False, dynamic=False)
    exported_path = Path(exported)
    if not exported_path.exists():
        exported_path = checkpoint.with_suffix(".onnx")
    if not exported_path.exists():
        raise RuntimeError("ONNX export did not produce a file")
    shutil.copy2(exported_path, output)
    return output


def train_and_export(
    data_yaml: str | Path = "datasets/forza_ui/yolo/data.yaml",
    base_model: str = "yolov8n.pt",
    epochs: int = 20,
    imgsz: int = 640,
    batch: int = 4,
    device: str = "cpu",
    project: str | Path = "v3/runs",
    name: str = "forza_ui_yolo",
    output: str | Path = "v3/models/forza_ui_yolo.onnx",
) -> Path:
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError(
            "Ultralytics is not installed. Install the training stack with:\n"
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements_vision.txt\n"
            "Then rerun this command."
        ) from exc

    data_yaml = Path(data_yaml)
    if not data_yaml.exists():
        raise RuntimeError(f"dataset data.yaml not found: {data_yaml}")
    project = Path(project)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    model = YOLO(base_model)
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        project=str(project),
        name=name,
        workers=0,
        verbose=True,
    )
    candidate_dirs = [
        project / name,
        Path("runs") / "detect" / project / name,
    ]
    trainer = getattr(model, "trainer", None)
    save_dir = getattr(trainer, "save_dir", None)
    if save_dir:
        candidate_dirs.insert(0, Path(save_dir))

    best_pt = None
    for candidate_dir in candidate_dirs:
        candidate = candidate_dir / "weights" / "best.pt"
        if candidate.exists():
            best_pt = candidate
            break
    if best_pt is None:
        searched = ", ".join(str(path / "weights" / "best.pt") for path in candidate_dirs)
        raise RuntimeError(f"training finished but best.pt was not found. searched: {searched}")
    return export_checkpoint(best_pt, imgsz=imgsz, output=output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train a lightweight YOLO model and export ONNX.")
    parser.add_argument("--data", default="datasets/forza_ui/yolo/data.yaml")
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--project", default="v3/runs")
    parser.add_argument("--name", default="forza_ui_yolo")
    parser.add_argument("--output", default="v3/models/forza_ui_yolo.onnx")
    parser.add_argument("--checkpoint", default="", help="Export an existing .pt checkpoint without retraining.")
    args = parser.parse_args(argv)
    if args.checkpoint:
        path = export_checkpoint(args.checkpoint, imgsz=args.imgsz, output=args.output)
    else:
        path = train_and_export(
            data_yaml=args.data,
            base_model=args.model,
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            project=args.project,
            name=args.name,
            output=args.output,
        )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
