"""
Model Inference Integration for PyFault AI framework.
"""

import asyncio
import logging
import time
import uuid
import hashlib
import json
import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union
from collections import defaultdict
import aiofiles

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ModelFormat(str, Enum):
    """Supported model formats."""
    ONNX = "onnx"
    TENSORFLOW = "tensorflow"
    PYTORCH = "pytorch"
    SKLEARN = "sklearn"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    TENSORRT = "tensorrt"
    OPENVINO = "openvino"
    CUSTOM = "custom"


class ModelStatus(str, Enum):
    """Model status."""
    PENDING = "pending"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"
    UNLOADED = "unloaded"


@dataclass
class ModelMetadata:
    """Model metadata."""
    model_id: str
    name: str
    version: str
    format: ModelFormat
    framework: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    size_bytes: int = 0
    checksum: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InferenceRequest:
    """Inference request."""
    model_id: str
    inputs: Dict[str, Any]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    priority: int = 0
    timeout_ms: int = 30000


@dataclass
class InferenceResult:
    """Inference result."""
    request_id: str
    model_id: str
    outputs: Dict[str, Any]
    latency_ms: float
    success: bool
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelBackend(ABC):
    """Abstract model backend."""
    
    @abstractmethod
    async def load(self, model_path: str, metadata: ModelMetadata) -> bool:
        """Load model from path."""
        pass
    
    @abstractmethod
    async def unload(self) -> bool:
        """Unload model."""
        pass
    
    @abstractmethod
    async def predict(self, inputs: Dict[str, Any], parameters: Dict = None) -> Dict[str, Any]:
        """Run inference."""
        pass
    
    @abstractmethod
    async def warmup(self) -> bool:
        """Warm up the model."""
        pass
    
    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        pass


class ModelRegistry:
    """
    Model registry for managing ML models.
    """
    
    def __init__(self, storage_path: str = "./data/models"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._models: Dict[str, "ModelInstance"] = {}
        self._metadata: Dict[str, ModelMetadata] = {}
        self._backends: Dict[str, ModelBackend] = {}
        self._loaded = False
    
    async def initialize(self) -> None:
        """Load models from storage."""
        await self._load_index()
        self._loaded = True
    
    async def _load_index(self) -> None:
        index_file = self.storage_path / "index.json"
        if index_file.exists():
            async with aiofiles.open(index_file, 'r') as f:
                data = json.loads(await f.read())
                for item in data:
                    metadata = ModelMetadata(**item)
                    self._metadata[metadata.model_id] = metadata
    
    async def _save_index(self) -> None:
        index_file = self.storage_path / "index.json"
        data = [meta.__dict__ for meta in self._metadata.values()]
        for meta in data:
            meta["created_at"] = meta["created_at"].isoformat() if isinstance(meta["created_at"], datetime) else meta["created_at"]
            meta["updated_at"] = meta["updated_at"].isoformat() if isinstance(meta["updated_at"], datetime) else meta["updated_at"]
        async with aiofiles.open(index_file, 'w') as f:
            await f.write(json.dumps(data, indent=2, default=str))
    
    async def register_model(self, metadata: ModelMetadata, model_path: str) -> bool:
        """Register a new model."""
        if metadata.model_id in self._metadata:
            return False
        
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        # Compute checksum
        with open(model_path, 'rb') as f:
            content = f.read()
            checksum = hashlib.sha256(content).hexdigest()
        
        metadata.checksum = checksum
        metadata.size_bytes = len(content)
        metadata.created_at = datetime.utcnow()
        metadata.updated_at = datetime.utcnow()
        
        self._metadata[metadata.model_id] = metadata
        await self._save_index()
        
        logger.info(f"Registered model: {metadata.name} v{metadata.version}")
        return True
    
    async def update_model(self, model_id: str, model_path: str, version: str = None) -> bool:
        """Update an existing model."""
        if model_id not in self._metadata:
            return False
        
        model_path = Path(model_path)
        if not model_path.exists():
            return False
        
        metadata = self._metadata[model_id]
        metadata.version = version or metadata.version
        metadata.updated_at = datetime.utcnow()
        
        with open(model_path, 'rb') as f:
            content = f.read()
            metadata.checksum = hashlib.sha256(content).hexdigest()
            metadata.size_bytes = len(content)
        
        await self._save_index()
        return True
    
    def get_model(self, model_id: str) -> Optional[ModelMetadata]:
        return self._metadata.get(model_id)
    
    def list_models(
        self,
        framework: Optional[str] = None,
        tags: List[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ModelMetadata]:
        models = list(self._metadata.values())
        
        if framework:
            models = [m for m in models if m.framework == framework]
        if tags:
            models = [m for m in models if any(tag in m.tags for tag in tags)]
        
        models.sort(key=lambda m: m.created_at, reverse=True)
        return models[offset:offset + limit]
    
    async def delete_model(self, model_id: str) -> bool:
        if model_id not in self._metadata:
            return False
        
        # Remove from loaded models if loaded
        if model_id in self._models:
            model = self._models[model_id]
            await model.unload()
            del self._models[model_id]
        
        del self._metadata[model_id]
        await self._save_index()
        return True


class ModelInstance:
    """Runtime model instance."""
    
    def __init__(self, metadata: ModelMetadata, backend):
        self.metadata = metadata
        self.backend = backend
        self._loaded = False
        self._load_time: Optional[datetime] = None
        self._invocation_count = 0
        self._total_latency_ms = 0.0
        self._error_count = 0
    
    @property
    def is_loaded(self) -> bool:
        return self._loaded
    
    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "model_id": self.metadata.model_id,
            "name": self.metadata.name,
            "version": self.metadata.version,
            "loaded": self._loaded,
            "load_time": self._load_time.isoformat() if self._load_time else None,
            "invocation_count": self._invocation_count,
            "avg_latency_ms": self._total_latency_ms / max(1, self._invocation_count),
            "error_rate": self._error_count / max(1, self._invocation_count),
        }
    
    async def load(self) -> bool:
        if self._loaded:
            return True
        
        try:
            success = await self.backend.load(self.metadata.model_id, self.metadata)
            if success:
                self._loaded = True
                self._load_time = datetime.utcnow()
                await self.warmup()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    async def unload(self) -> bool:
        if not self._loaded:
            return True
        
        try:
            success = await self.backend.unload()
            if success:
                self._loaded = False
                self._load_time = None
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to unload model: {e}")
            return False
    
    async def warmup(self) -> bool:
        if not self._loaded:
            return False
        return await self.backend.warmup()
    
    async def predict(self, inputs: Dict[str, Any], parameters: Dict = None) -> Dict[str, Any]:
        if not self._loaded:
            await self.load()
        
        if not self._loaded:
            raise RuntimeError("Model not loaded")
        
        start = time.time()
        self._invocation_count += 1
        
        try:
            outputs = await self.backend.predict(inputs, parameters or {})
            self._total_latency_ms += (time.time() - start) * 1000
            return {
                "outputs": outputs,
                "latency_ms": (time.time() - start) * 1000,
            }
        except Exception as e:
            self._error_count += 1
            raise


class InferenceEngine:
    """
    High-level inference engine for managing multiple models.
    """
    
    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self._models: Dict[str, ModelInstance] = {}
        self._backends: Dict[str, ModelBackend] = {}
    
    def register_backend(self, format: str, backend: ModelBackend) -> None:
        self._backends[format] = backend
    
    async def load_model(self, model_id: str) -> bool:
        """Load a model into memory."""
        metadata = self.registry.get_model(model_id)
        if not metadata:
            raise ValueError(f"Model not found: {model_id}")
        
        if model_id in self._models:
            return self._models[model_id].is_loaded
        
        backend = self._backends.get(metadata.format.value)
        if not backend:
            raise ValueError(f"No backend for format: {metadata.format}")
        
        model = ModelInstance(metadata, backend)
        success = await model.load()
        
        if success:
            self._models[model_id] = model
            return True
        return False
    
    async def unload_model(self, model_id: str) -> bool:
        if model_id not in self._models:
            return False
        
        model = self._models[model_id]
        success = await model.unload()
        if success:
            del self._models[model_id]
            return True
        return False
    
    async def predict(
        self,
        model_id: str,
        inputs: Dict[str, Any],
        parameters: Dict = None,
    ) -> InferenceResult:
        """Run inference on a model."""
        if model_id not in self._models:
            await self.load_model(model_id)
        
        model = self._models.get(model_id)
        if not model:
            return InferenceResult(
                request_id=str(uuid.uuid4()),
                model_id=model_id,
                outputs={},
                latency_ms=0,
                success=False,
                error_message=f"Model not found: {model_id}",
            )
        
        start = time.time()
        try:
            result = await model.predict(inputs, parameters or {})
            return InferenceResult(
                request_id=str(uuid.uuid4()),
                model_id=model_id,
                outputs=result["outputs"],
                latency_ms=result["latency_ms"],
                success=True,
            )
        except Exception as e:
            return InferenceResult(
                request_id=str(uuid.uuid4()),
                model_id=model_id,
                outputs={},
                latency_ms=(time.time() - start) * 1000,
                success=False,
                error_message=str(e),
            )
    
    async def batch_predict(
        self,
        model_id: str,
        inputs_batch: List[Dict[str, Any]],
        parameters: Dict = None,
    ) -> List[InferenceResult]:
        """Batch inference."""
        results = []
        for inputs in inputs_batch:
            result = await self.predict(model_id, inputs, parameters)
            results.append(result)
        return results
    
    async def warmup_model(self, model_id: str) -> bool:
        if model_id in self._models:
            return await self._models[model_id].warmup()
        return False
    
    def get_model_stats(self, model_id: str) -> Optional[Dict[str, Any]]:
        if model_id in self._models:
            return self._models[model_id].stats
        return None
    
    def list_loaded_models(self) -> List[Dict[str, Any]]:
        return [m.stats for m in self._models.values()]
    
    def get_model_info(self, model_id: str) -> Optional[Dict]:
        if model_id in self._models:
            return self._models[model_id].stats
        elif model_id in self.registry._metadata:
            return self.registry._metadata[model_id].__dict__
        return None


class ModelServer:
    """
    High-level model serving interface.
    """
    
    def __init__(self, registry: ModelRegistry = None, storage_path: str = "./data/models"):
        self.registry = registry or ModelRegistry(storage_path)
        self.engine = InferenceEngine(self.registry)
        self._server = None
    
    async def initialize(self) -> None:
        await self.registry.initialize()
    
    def register_backend(self, format: str, backend: ModelBackend):
        self.engine.register_backend(format, backend)
    
    async def deploy_model(
        self,
        model_id: str,
        name: str,
        version: str,
        format: ModelFormat,
        model_path: str,
        input_schema: Dict = None,
        output_schema: Dict = None,
    ) -> bool:
        """Deploy a model."""
        metadata = ModelMetadata(
            model_id=model_id,
            name=name,
            version=version,
            format=format,
            framework=framework,
            input_schema=input_schema or {},
            output_schema=output_schema or {},
        )
        
        success = await self.registry.register_model(metadata, model_path)
        if not success:
            return False
        
        return await self.engine.load_model(model_id)
    
    async def predict(
        self,
        model_id: str,
        inputs: Dict[str, Any],
        parameters: Dict = None,
    ) -> InferenceResult:
        return await self.engine.predict(model_id, inputs, parameters)
    
    async def batch_predict(
        self,
        model_id: str,
        inputs_batch: List[Dict[str, Any]],
        parameters: Dict = None,
    ) -> List[InferenceResult]:
        return await self.engine.batch_predict(model_id, inputs_batch, parameters)
    
    def get_model_info(self, model_id: str) -> Optional[Dict]:
        return self.engine.get_model_info(model_id)
    
    def list_models(self, **kwargs) -> List[Dict]:
        return [m.__dict__ for m in self.registry.list_models(**kwargs)]
    
    async def undeploy_model(self, model_id: str) -> bool:
        await self.engine.unload_model(model_id)
        return await self.registry.delete_model(model_id)
    
    def get_stats(self) -> Dict:
        return {
            "loaded_models": len(self.engine._models),
            "registered_models": len(self.registry._metadata),
            "models": self.list_loaded_models(),
        }
    
    def list_loaded_models(self) -> List[Dict]:
        return self.engine.list_loaded_models()


# Global instances
_model_registry: Optional[ModelRegistry] = None
_inference_engine: Optional[InferenceEngine] = None
_model_server: Optional[ModelServer] = None


def get_model_registry(storage_path: str = "./data/models") -> ModelRegistry:
    global _model_registry
    if _model_registry is None:
        _model_registry = ModelRegistry(storage_path)
    return _model_registry


def get_inference_engine(registry: ModelRegistry = None) -> InferenceEngine:
    global _inference_engine
    if _inference_engine is None:
        _inference_engine = InferenceEngine(registry or get_model_registry())
    return _inference_engine


def get_model_server(registry: ModelRegistry = None) -> ModelServer:
    global _model_server
    if _model_server is None:
        _model_server = ModelServer(registry)
    return _model_server


# Aliases for backward compatibility
get_inference_engine = get_inference_engine
get_model_registry = get_model_registry
get_model_server = get_model_server