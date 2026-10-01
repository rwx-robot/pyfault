"""
Model Inference Backends for PyFault AI framework.

Provides concrete implementations for various ML frameworks:
- ONNX Runtime
- PyTorch
- TensorFlow/Keras
- scikit-learn
- XGBoost/LightGBM
- TensorRT
- OpenVINO
- Custom backends
"""

import asyncio
import logging
import random
import time
import uuid
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy as np

from pyfault.common.time import utc_now

# Suppress common warnings
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger(__name__)


@dataclass
class BackendConfig:
    """Configuration for a model backend."""
    backend_id: str
    model_path: str
    device: str = "cpu"  # cpu, cuda, cuda:0, mps
    batch_size: int = 1
    num_threads: int = 0  # 0 = auto
    optimization_level: int = 1  # 0=none, 1=basic, 2=extended, 3=all
    enable_profiling: bool = False
    custom_options: dict[str, Any] = field(default_factory=dict)


class InferenceBackend(ABC):
    """Abstract base class for inference backends."""

    def __init__(self, config: BackendConfig):
        self.config = config
        self._model: Any = None
        self._session: Any = None
        self._input_names: list[str] = []
        self._output_names: list[str] = []
        self._input_shapes: dict[str, tuple] = {}
        self._output_shapes: dict[str, tuple] = {}
        self._loaded = False
        self._load_time: Optional[datetime] = None
        self._invocation_count = 0
        self._total_latency_ms = 0.0

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @abstractmethod
    async def load(self) -> bool:
        """Load the model."""
        pass

    @abstractmethod
    async def unload(self) -> bool:
        """Unload the model."""
        pass

    @abstractmethod
    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        """Run inference."""
        pass

    @abstractmethod
    async def warmup(self, num_runs: int = 3) -> bool:
        """Warm up the model."""
        pass

    @abstractmethod
    def get_input_info(self) -> dict[str, Any]:
        """Get input tensor information."""
        pass

    @abstractmethod
    def get_output_info(self) -> dict[str, Any]:
        """Get output tensor information."""
        pass

    def get_stats(self) -> dict[str, Any]:
        return {
            "backend_id": self.config.backend_id,
            "model_path": self.config.model_path,
            "device": self.config.device,
            "loaded": self._loaded,
            "load_time": self._load_time.isoformat() if self._load_time else None,
            "invocation_count": self._invocation_count,
            "avg_latency_ms": self._total_latency_ms / max(1, self._invocation_count),
        }

    def _record_invocation(self, latency_ms: float) -> None:
        self._invocation_count += 1
        self._total_latency_ms += latency_ms


class ONNXBackend(InferenceBackend):
    """ONNX Runtime backend."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._session_options: Any = None
        self._providers: list[str] = []

    async def load(self) -> bool:
        try:
            import onnxruntime as ort
        except ImportError:
            logger.error("onnxruntime not installed. Install with: pip install onnxruntime")
            return False

        try:
            # Configure session options
            self._session_options = ort.SessionOptions()
            self._session_options.optimization_level = ort.GraphOptimizationLevel(self.config.optimization_level)

            if self.config.num_threads > 0:
                self._session_options.intra_op_num_threads = self.config.num_threads
                self._session_options.inter_op_num_threads = self.config.num_threads

            if self.config.enable_profiling:
                self._session_options.enable_profiling = True

            # Determine execution providers
            self._providers = self._get_providers()

            # Load model
            self._session = ort.InferenceSession(
                self.config.model_path,
                self._session_options,
                providers=self._providers,
            )

            # Get input/output info
            self._input_names = [inp.name for inp in self._session.get_inputs()]
            self._output_names = [out.name for out in self._session.get_outputs()]

            for inp in self._session.get_inputs():
                self._input_shapes[inp.name] = tuple(inp.shape)

            for out in self._session.get_outputs():
                self._output_shapes[out.name] = tuple(out.shape)

            self._loaded = True
            self._load_time = utc_now()
            logger.info(f"ONNX model loaded: {self.config.model_path} on {self._providers}")
            return True

        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}")
            return False

    def _get_providers(self) -> list[str]:
        device = self.config.device.lower()
        if device.startswith("cuda"):
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        elif device == "mps":
            return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        elif device == "tensorrt":
            return ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            return ["CPUExecutionProvider"]

    async def unload(self) -> bool:
        self._session = None
        self._loaded = False
        return True

    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        if not self._loaded:
            raise RuntimeError("Model not loaded")

        start = time.perf_counter()

        try:
            # Validate inputs
            for name in self._input_names:
                if name not in inputs:
                    raise ValueError(f"Missing required input: {name}")

            # Run inference
            outputs = self._session.run(
                self._output_names,
                {name: inputs[name] for name in self._input_names},
            )

            result = dict(zip(self._output_names, outputs))

            latency_ms = (time.perf_counter() - start) * 1000
            self._record_invocation(latency_ms)

            return result

        except Exception as e:
            logger.error(f"ONNX inference error: {e}")
            raise

    async def warmup(self, num_runs: int = 3) -> bool:
        if not self._loaded:
            return False

        try:
            # Create dummy inputs
            dummy_inputs = {}
            for inp in self._session.get_inputs():
                shape = tuple(dim if dim > 0 else 1 for dim in inp.shape)
                if inp.type.startswith("tensor(float"):
                    dummy_inputs[inp.name] = np.random.randn(*shape).astype(np.float32)
                elif inp.type.startswith("tensor(int"):
                    dummy_inputs[inp.name] = np.random.randint(0, 100, shape).astype(np.int64)
                else:
                    dummy_inputs[inp.name] = np.ones(shape, dtype=np.float32)

            for _ in range(num_runs):
                await self.predict(dummy_inputs)

            logger.info(f"ONNX model warmed up: {self.config.model_path}")
            return True
        except Exception as e:
            logger.error(f"ONNX warmup failed: {e}")
            return False

    def get_input_info(self) -> dict[str, Any]:
        return {
            "names": self._input_names,
            "shapes": self._input_shapes,
        }

    def get_output_info(self) -> dict[str, Any]:
        return {
            "names": self._output_names,
            "shapes": self._output_shapes,
        }


class PyTorchBackend(InferenceBackend):
    """PyTorch backend."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._device: Any = None
        self._model_class: Any = None

    async def load(self) -> bool:
        try:
            import torch
        except ImportError:
            logger.error("torch not installed. Install with: pip install torch")
            return False

        try:
            # Determine device
            if self.config.device.startswith("cuda") and torch.cuda.is_available():
                self._device = torch.device(self.config.device)
            elif self.config.device == "mps" and torch.backends.mps.is_available():
                self._device = torch.device("mps")
            else:
                self._device = torch.device("cpu")

            # Load model
            # Support both .pt/.pth (state_dict) and full model
            if self.config.model_path.endswith((".pt", ".pth")):
                # Try loading as full model first
                try:
                    self._model = torch.jit.load(self.config.model_path, map_location=self._device)
                except Exception:
                    # Load state dict
                    state_dict = torch.load(self.config.model_path, map_location=self._device)
                    # User must provide model class via custom_options
                    model_class = self.config.custom_options.get("model_class")
                    if not model_class:
                        raise ValueError(
                            "model_class required in custom_options for state_dict loading"
                        ) from None
                    self._model = model_class()
                    self._model.load_state_dict(state_dict)
            else:
                # Try TorchScript
                self._model = torch.jit.load(self.config.model_path, map_location=self._device)

            self._model.to(self._device)
            self._model.eval()

            # Try to get input/output info from model
            self._infer_io_info()

            self._loaded = True
            self._load_time = utc_now()
            logger.info(f"PyTorch model loaded: {self.config.model_path} on {self._device}")
            return True

        except Exception as e:
            logger.error(f"Failed to load PyTorch model: {e}")
            return False

    def _infer_io_info(self) -> None:
        # Try to infer from model
        try:
            import torch
            # Check if it's a scripted module with schema
            if hasattr(self._model, 'graph'):
                for inp in self._model.graph.inputs():
                    self._input_names.append(inp.debugName())
                for out in self._model.graph.outputs():
                    self._output_names.append(out.debugName())
        except Exception:
            pass

    async def unload(self) -> bool:
        import torch
        self._model = None
        if self._device and self._device.type == "cuda":
            torch.cuda.empty_cache()
        self._loaded = False
        return True

    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        import torch

        if not self._loaded:
            raise RuntimeError("Model not loaded")

        start = time.perf_counter()

        try:
            # Convert inputs to tensors
            tensor_inputs = {}
            for name, array in inputs.items():
                tensor_inputs[name] = torch.from_numpy(array).to(self._device)

            # Run inference
            with torch.no_grad():
                if len(tensor_inputs) == 1:
                    # Single input
                    input_tensor = list(tensor_inputs.values())[0]
                    output = self._model(input_tensor)
                else:
                    # Multiple inputs - try as kwargs
                    output = self._model(**tensor_inputs)

            # Convert output to dict
            result = {}
            if isinstance(output, tuple):
                for i, out in enumerate(output):
                    name = self._output_names[i] if i < len(self._output_names) else f"output_{i}"
                    result[name] = out.cpu().numpy()
            elif isinstance(output, dict):
                for name, tensor in output.items():
                    result[name] = tensor.cpu().numpy()
            else:
                name = self._output_names[0] if self._output_names else "output"
                result[name] = output.cpu().numpy()

            latency_ms = (time.perf_counter() - start) * 1000
            self._record_invocation(latency_ms)

            return result

        except Exception as e:
            logger.error(f"PyTorch inference error: {e}")
            raise

    async def warmup(self, num_runs: int = 3) -> bool:
        if not self._loaded:
            return False

        try:
            import torch
            # Create dummy inputs
            dummy_inputs = {}
            for name in self._input_names:
                shape = (self.config.batch_size, 3, 224, 224)  # Default
                dummy_inputs[name] = torch.randn(shape).to(self._device)

            with torch.no_grad():
                for _ in range(num_runs):
                    _ = self._model(**dummy_inputs) if len(dummy_inputs) > 1 else self._model(list(dummy_inputs.values())[0])

            logger.info(f"PyTorch model warmed up: {self.config.model_path}")
            return True
        except Exception as e:
            logger.error(f"PyTorch warmup failed: {e}")
            return False

    def get_input_info(self) -> dict[str, Any]:
        return {"names": self._input_names}

    def get_output_info(self) -> dict[str, Any]:
        return {"names": self._output_names}


class TensorFlowBackend(InferenceBackend):
    """TensorFlow/Keras backend."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._model = None

    async def load(self) -> bool:
        try:
            import tensorflow as tf
        except ImportError:
            logger.error("tensorflow not installed. Install with: pip install tensorflow")
            return False

        try:
            # Configure GPU if needed
            if self.config.device.startswith("cuda"):
                gpus = tf.config.list_physical_devices('GPU')
                if gpus:
                    for gpu in gpus:
                        tf.config.experimental.set_memory_growth(gpu, True)

            # Load model
            self._model = tf.keras.models.load_model(self.config.model_path)

            # Get input/output info
            self._input_names = [inp.name.split(':')[0] for inp in self._model.inputs]
            self._output_names = [out.name.split(':')[0] for out in self._model.outputs]

            for inp in self._model.inputs:
                self._input_shapes[inp.name.split(':')[0]] = tuple(inp.shape.as_list())
            for out in self._model.outputs:
                self._output_shapes[out.name.split(':')[0]] = tuple(out.shape.as_list())

            self._loaded = True
            self._load_time = utc_now()
            logger.info(f"TensorFlow model loaded: {self.config.model_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load TensorFlow model: {e}")
            return False

    async def unload(self) -> bool:
        import tensorflow as tf
        self._model = None
        tf.keras.backend.clear_session()
        self._loaded = False
        return True

    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        import tensorflow as tf

        if not self._loaded:
            raise RuntimeError("Model not loaded")

        start = time.perf_counter()

        try:
            # Prepare inputs in correct order
            if len(self._input_names) == 1:
                input_data: Any = inputs[self._input_names[0]]
            else:
                input_data = [inputs[name] for name in self._input_names]

            # Run inference
            outputs = self._model.predict(input_data, batch_size=self.config.batch_size, verbose=0)

            # Convert to dict
            result = {}
            if isinstance(outputs, list):
                for i, out in enumerate(outputs):
                    name = self._output_names[i] if i < len(self._output_names) else f"output_{i}"
                    result[name] = out
            elif isinstance(outputs, dict):
                result = outputs
            else:
                name = self._output_names[0] if self._output_names else "output"
                result[name] = outputs

            latency_ms = (time.perf_counter() - start) * 1000
            self._record_invocation(latency_ms)

            return result

        except Exception as e:
            logger.error(f"TensorFlow inference error: {e}")
            raise

    async def warmup(self, num_runs: int = 3) -> bool:
        if not self._loaded:
            return False

        try:
            # Create dummy inputs
            dummy_inputs = {}
            for name, shape in self._input_shapes.items():
                # Replace None with 1
                shape = tuple(1 if dim is None else dim for dim in shape)
                dummy_inputs[name] = np.random.randn(*shape).astype(np.float32)

            for _ in range(num_runs):
                _ = self._model.predict(
                    dummy_inputs if len(dummy_inputs) > 1 else list(dummy_inputs.values())[0],
                    batch_size=self.config.batch_size,
                    verbose=0
                )

            logger.info(f"TensorFlow model warmed up: {self.config.model_path}")
            return True
        except Exception as e:
            logger.error(f"TensorFlow warmup failed: {e}")
            return False

    def get_input_info(self) -> dict[str, Any]:
        return {
            "names": self._input_names,
            "shapes": self._input_shapes,
        }

    def get_output_info(self) -> dict[str, Any]:
        return {
            "names": self._output_names,
            "shapes": self._output_shapes,
        }


class SklearnBackend(InferenceBackend):
    """scikit-learn backend."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._model = None
        self._scaler: Any = None

    async def load(self) -> bool:
        try:
            import joblib
        except ImportError:
            logger.error("joblib not installed. Install with: pip install joblib")
            return False

        try:
            # Load model
            self._model = joblib.load(self.config.model_path)

            # Check if it's a pipeline with scaler
            if hasattr(self._model, 'named_steps'):
                for name, step in self._model.named_steps.items():
                    if hasattr(step, 'transform') and 'scaler' in name.lower():
                        self._scaler = step

            # Try to get feature names
            if hasattr(self._model, 'feature_names_in_'):
                self._input_names = list(self._model.feature_names_in_)
            else:
                self._input_names = ["input"]

            if hasattr(self._model, 'classes_'):
                self._output_names = ["prediction", "probability"]
            else:
                self._output_names = ["output"]

            self._loaded = True
            self._load_time = utc_now()
            logger.info(f"sklearn model loaded: {self.config.model_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load sklearn model: {e}")
            return False

    async def unload(self) -> bool:
        self._model = None
        self._scaler = None
        self._loaded = False
        return True

    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        if not self._loaded:
            raise RuntimeError("Model not loaded")

        start = time.perf_counter()

        try:
            # Get input array
            if len(self._input_names) == 1:
                X = inputs[self._input_names[0]]
            else:
                # Concatenate multiple inputs
                X = np.column_stack([inputs[name] for name in self._input_names])

            # Apply scaler if present
            if self._scaler:
                X = self._scaler.transform(X)

            # Predict
            if hasattr(self._model, 'predict_proba'):
                pred = self._model.predict(X)
                proba = self._model.predict_proba(X)
                result = {
                    "prediction": pred,
                    "probability": proba,
                }
            else:
                pred = self._model.predict(X)
                result = {"output": pred}

            latency_ms = (time.perf_counter() - start) * 1000
            self._record_invocation(latency_ms)

            return result

        except Exception as e:
            logger.error(f"sklearn inference error: {e}")
            raise

    async def warmup(self, num_runs: int = 3) -> bool:
        if not self._loaded:
            return False

        try:
            # Create dummy input with the model's real feature count
            n_features = getattr(self._model, "n_features_in_", None)
            if n_features is None:
                n_features = len(self._input_names)
            dummy = np.random.randn(self.config.batch_size, n_features).astype(np.float32)
            if len(self._input_names) == 1:
                dummy_inputs = {self._input_names[0]: dummy}
            else:
                dummy_inputs = {
                    name: dummy[:, i : i + 1]
                    for i, name in enumerate(self._input_names)
                }

            for _ in range(num_runs):
                await self.predict(dummy_inputs)

            logger.info(f"sklearn model warmed up: {self.config.model_path}")
            return True
        except Exception as e:
            logger.error(f"sklearn warmup failed: {e}")
            return False

    def get_input_info(self) -> dict[str, Any]:
        return {"names": self._input_names}

    def get_output_info(self) -> dict[str, Any]:
        return {"names": self._output_names}


class XGBoostBackend(InferenceBackend):
    """XGBoost backend."""

    async def load(self) -> bool:
        try:
            import xgboost as xgb
        except ImportError:
            logger.error("xgboost not installed. Install with: pip install xgboost")
            return False

        try:
            self._model = xgb.Booster()
            self._model.load_model(self.config.model_path)

            self._input_names = ["input"]
            self._output_names = ["prediction"]

            self._loaded = True
            self._load_time = utc_now()
            logger.info(f"XGBoost model loaded: {self.config.model_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load XGBoost model: {e}")
            return False

    async def unload(self) -> bool:
        self._model = None
        self._loaded = False
        return True

    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        import xgboost as xgb

        if not self._loaded:
            raise RuntimeError("Model not loaded")

        start = time.perf_counter()

        try:
            X = inputs["input"]
            dmatrix = xgb.DMatrix(X)
            pred = self._model.predict(dmatrix)

            result = {"prediction": pred}

            latency_ms = (time.perf_counter() - start) * 1000
            self._record_invocation(latency_ms)

            return result
        except Exception as e:
            logger.error(f"XGBoost inference error: {e}")
            raise

    async def warmup(self, num_runs: int = 3) -> bool:
        if not self._loaded:
            return False

        try:
            dummy = np.random.randn(self.config.batch_size, 10).astype(np.float32)
            for _ in range(num_runs):
                await self.predict({"input": dummy})
            return True
        except Exception as e:
            logger.error(f"XGBoost warmup failed: {e}")
            return False

    def get_input_info(self) -> dict[str, Any]:
        return {"names": self._input_names}

    def get_output_info(self) -> dict[str, Any]:
        return {"names": self._output_names}


class LightGBMBackend(InferenceBackend):
    """LightGBM backend."""

    async def load(self) -> bool:
        try:
            import lightgbm as lgb
        except ImportError:
            logger.error("lightgbm not installed. Install with: pip install lightgbm")
            return False

        try:
            self._model = lgb.Booster(model_file=self.config.model_path)

            self._input_names = ["input"]
            self._output_names = ["prediction"]

            self._loaded = True
            self._load_time = utc_now()
            logger.info(f"LightGBM model loaded: {self.config.model_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load LightGBM model: {e}")
            return False

    async def unload(self) -> bool:
        self._model = None
        self._loaded = False
        return True

    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        if not self._loaded:
            raise RuntimeError("Model not loaded")

        start = time.perf_counter()

        try:
            X = inputs["input"]
            pred = self._model.predict(X)

            result = {"prediction": pred}

            latency_ms = (time.perf_counter() - start) * 1000
            self._record_invocation(latency_ms)

            return result
        except Exception as e:
            logger.error(f"LightGBM inference error: {e}")
            raise

    async def warmup(self, num_runs: int = 3) -> bool:
        if not self._loaded:
            return False

        try:
            dummy = np.random.randn(self.config.batch_size, 10).astype(np.float32)
            for _ in range(num_runs):
                await self.predict({"input": dummy})
            return True
        except Exception as e:
            logger.error(f"LightGBM warmup failed: {e}")
            return False

    def get_input_info(self) -> dict[str, Any]:
        return {"names": self._input_names}

    def get_output_info(self) -> dict[str, Any]:
        return {"names": self._output_names}


class CustomBackend(InferenceBackend):
    """Custom backend with user-defined inference function."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._predict_fn: Any = None
        self._load_fn: Any = None
        self._unload_fn: Any = None
        self._warmup_fn: Any = None

    def set_functions(
        self,
        predict_fn: Callable,
        load_fn: Optional[Callable] = None,
        unload_fn: Optional[Callable] = None,
        warmup_fn: Optional[Callable] = None,
    ) -> None:
        self._predict_fn = predict_fn
        self._load_fn = load_fn
        self._unload_fn = unload_fn
        self._warmup_fn = warmup_fn

    async def load(self) -> bool:
        if self._load_fn:
            try:
                if asyncio.iscoroutinefunction(self._load_fn):
                    await self._load_fn(self.config)
                else:
                    self._load_fn(self.config)
            except Exception as e:
                logger.error(f"Custom load function failed: {e}")
                return False

        self._loaded = True
        self._load_time = utc_now()
        return True

    async def unload(self) -> bool:
        if self._unload_fn:
            try:
                if asyncio.iscoroutinefunction(self._unload_fn):
                    await self._unload_fn()
                else:
                    self._unload_fn()
            except Exception as e:
                logger.error(f"Custom unload function failed: {e}")
                return False

        self._loaded = False
        return True

    async def predict(
        self,
        inputs: dict[str, np.ndarray],
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, np.ndarray]:
        if not self._loaded or not self._predict_fn:
            raise RuntimeError("Model not loaded or predict function not set")

        start = time.perf_counter()

        try:
            if asyncio.iscoroutinefunction(self._predict_fn):
                result: dict[str, np.ndarray] = await self._predict_fn(inputs, parameters or {})
            else:
                result = self._predict_fn(inputs, parameters or {})

            latency_ms = (time.perf_counter() - start) * 1000
            self._record_invocation(latency_ms)

            return result
        except Exception as e:
            logger.error(f"Custom inference error: {e}")
            raise

    async def warmup(self, num_runs: int = 3) -> bool:
        if self._warmup_fn:
            try:
                if asyncio.iscoroutinefunction(self._warmup_fn):
                    await self._warmup_fn(num_runs)
                else:
                    self._warmup_fn(num_runs)
                return True
            except Exception as e:
                logger.error(f"Custom warmup failed: {e}")
                return False
        return True

    def get_input_info(self) -> dict[str, Any]:
        return {}

    def get_output_info(self) -> dict[str, Any]:
        return {}


# Backend factory
BACKEND_REGISTRY: dict[str, Callable[[BackendConfig], InferenceBackend]] = {
    "onnx": ONNXBackend,
    "pytorch": PyTorchBackend,
    "torch": PyTorchBackend,
    "tensorflow": TensorFlowBackend,
    "tf": TensorFlowBackend,
    "keras": TensorFlowBackend,
    "sklearn": SklearnBackend,
    "scikit-learn": SklearnBackend,
    "xgboost": XGBoostBackend,
    "lightgbm": LightGBMBackend,
    "lgbm": LightGBMBackend,
    "custom": CustomBackend,
}


def create_backend(backend_type: str, config: BackendConfig) -> InferenceBackend:
    """Create a backend instance."""
    backend_type = backend_type.lower()
    if backend_type not in BACKEND_REGISTRY:
        raise ValueError(f"Unknown backend type: {backend_type}. Available: {list(BACKEND_REGISTRY.keys())}")

    backend_class = BACKEND_REGISTRY[backend_type]
    return backend_class(config)


def register_backend(name: str, backend_class: Callable[[BackendConfig], InferenceBackend]) -> None:
    """Register a custom backend."""
    BACKEND_REGISTRY[name.lower()] = backend_class


def get_available_backends() -> list[str]:
    return list(BACKEND_REGISTRY.keys())


# For backward compatibility
get_available_backends = get_available_backends
