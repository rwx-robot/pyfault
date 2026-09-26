"""
Admin WebSocket Handler for PyFault framework.
"""

import asyncio
import contextlib
import json
from typing import Any, Optional

from pyfault.common.plugins import get_plugin_manager
from pyfault.common.tenant import get_current_tenant


class AdminWebSocketHandler:
    """WebSocket handler for real-time admin updates."""

    def __init__(self) -> None:
        self._clients: set[Any] = set()
        self._subscriptions: dict[str, set[Any]] = {}
        self._running = False
        self._update_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: Any) -> None:
        """Handle new WebSocket connection."""
        await websocket.accept()
        self._clients.add(websocket)

        # Send initial state
        await self._send_initial_state(websocket)

    async def disconnect(self, websocket: Any) -> None:
        """Handle WebSocket disconnection."""
        self._clients.discard(websocket)

        # Remove from all subscriptions
        for _topic, clients in self._subscriptions.items():
            clients.discard(websocket)

    async def handle_message(self, websocket: Any, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            action = data.get("action")

            if action == "subscribe":
                await self._handle_subscribe(websocket, data)
            elif action == "unsubscribe":
                await self._handle_unsubscribe(websocket, data)
            elif action == "command":
                await self._handle_command(websocket, data)
            elif action == "ping":
                await websocket.send_json({"type": "pong"})

        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "message": "Invalid JSON"})
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})

    async def _handle_subscribe(self, websocket: Any, data: dict[str, Any]) -> None:
        """Handle subscription request."""
        topic = data.get("topic")
        if not topic:
            return

        if topic not in self._subscriptions:
            self._subscriptions[topic] = set()

        self._subscriptions[topic].add(websocket)
        await websocket.send_json({
            "type": "subscribed",
            "topic": topic,
        })

    async def _handle_unsubscribe(self, websocket: Any, data: dict[str, Any]) -> None:
        """Handle unsubscribe request."""
        topic = data.get("topic")
        if topic and topic in self._subscriptions:
            self._subscriptions[topic].discard(websocket)
            await websocket.send_json({
                "type": "unsubscribed",
                "topic": topic,
            })

    async def _handle_command(self, websocket: Any, data: dict[str, Any]) -> None:
        """Handle admin command."""
        command = data.get("command")
        payload = data.get("payload", {})

        if command == "start_plugin":
            await self._cmd_start_plugin(websocket, payload)
        elif command == "stop_plugin":
            await self._cmd_stop_plugin(websocket, payload)
        elif command == "restart_plugin":
            await self._cmd_restart_plugin(websocket, payload)
        elif command == "update_config":
            await self._cmd_update_config(websocket, payload)
        elif command == "refresh_metrics":
            await self._cmd_refresh_metrics(websocket)

    async def _cmd_start_plugin(self, websocket: Any, payload: dict[str, Any]) -> None:
        """Start a plugin."""
        plugin_name = payload.get("plugin")
        if not plugin_name:
            await websocket.send_json({"type": "error", "message": "Plugin name required"})
            return


        try:
            await get_plugin_manager().start_plugins([payload["plugin"]])
            await websocket.send_json({
                "type": "plugin_started",
                "plugin": payload["plugin"],
            })
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})

    async def _cmd_stop_plugin(self, websocket: Any, payload: dict[str, Any]) -> None:
        """Stop a plugin."""
        plugin_name = payload.get("plugin")
        if not plugin_name:
            await websocket.send_json({"type": "error", "message": "Plugin name required"})
            return


        try:
            await get_plugin_manager().stop_plugins([payload["plugin"]])
            await websocket.send_json({
                "type": "plugin_stopped",
                "plugin": payload["plugin"],
            })
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})

    async def _cmd_restart_plugin(self, websocket: Any, payload: dict[str, Any]) -> None:
        """Restart a plugin."""
        plugin_name = payload.get("plugin")
        if not plugin_name:
            await websocket.send_json({"type": "error", "message": "Plugin name required"})
            return


        try:
            await get_plugin_manager().reload_plugin(payload["plugin"])
            await websocket.send_json({
                "type": "plugin_restarted",
                "plugin": payload["plugin"],
            })
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})

    async def _cmd_update_config(self, websocket: Any, payload: dict[str, Any]) -> None:
        """Update plugin configuration."""
        plugin_name = payload.get("plugin")
        config = payload.get("config", {})

        if not plugin_name:
            await websocket.send_json({"type": "error", "message": "Plugin name required"})
            return


        plugin_manager = get_plugin_manager()
        try:
            plugin_manager.update_config(plugin_name, config)
            await websocket.send_json({
                "type": "config_updated",
                "plugin": plugin_name,
            })
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})

    async def _cmd_refresh_metrics(self, websocket: Any) -> None:
        """Refresh and send metrics."""
        await self._broadcast_metrics()

    async def _send_initial_state(self, websocket: Any) -> None:
        """Send initial state to new client."""

        plugin_manager = get_plugin_manager()
        plugins = {}
        for name, plugin in plugin_manager.get_all_plugins().items():
            plugins[name] = {
                "name": name,
                "state": plugin.state.value,
                "version": plugin.metadata.version if plugin.metadata else "unknown",
            }

        tenant = get_current_tenant()

        await websocket.send_json({
            "type": "initial_state",
            "data": {
                "plugins": plugins,
                "tenant": tenant.id if tenant else "default",
                "version": "1.4.0",
            },
        })

    async def _broadcast(self, message: dict[str, Any], topic: Optional[str] = None) -> None:
        """Broadcast message to all clients or topic subscribers."""
        targets = self._clients

        if topic and topic in self._subscriptions:
            targets = self._subscriptions[topic]

        disconnected = set()

        for client in targets:
            try:
                await client.send_text(json.dumps(message))
            except Exception:
                disconnected.add(client)

        # Clean up disconnected clients
        for client in disconnected:
            self._clients.discard(client)
            for topic_clients in self._subscriptions.values():
                topic_clients.discard(client)

    async def broadcast_plugin_update(self, plugin_name: str, state: str) -> None:
        """Broadcast plugin state update."""
        await self._broadcast({
            "type": "plugin_update",
            "plugin": plugin_name,
            "state": state,
        }, "plugins")

    async def broadcast_metrics(self, metrics: dict[str, Any]) -> None:
        """Broadcast metrics update."""
        await self._broadcast({
            "type": "metrics_update",
            "data": metrics,
        }, "metrics")

    async def broadcast_health(self, health: dict[str, Any]) -> None:
        """Broadcast health update."""
        await self._broadcast({
            "type": "health_update",
            "data": health,
        }, "health")

    async def broadcast_log(self, log_entry: dict[str, Any]) -> None:
        """Broadcast log entry."""
        await self._broadcast({
            "type": "log",
            "data": log_entry,
        }, "logs")

    async def start_periodic_updates(self, interval: float = 5.0) -> None:
        """Start periodic updates broadcast."""
        self._running = True
        self._update_task = asyncio.create_task(self._update_loop(interval))

    async def stop_periodic_updates(self) -> None:
        """Stop periodic updates."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task

    async def _update_loop(self, interval: float) -> None:
        """Periodic update loop."""
        while self._running:
            try:
                await self._broadcast_metrics()
                await self._broadcast_health()
            except Exception:
                pass
            await asyncio.sleep(interval)

    async def _broadcast_metrics(self) -> None:
        """Broadcast current metrics."""
        metrics_plugin = get_plugin_manager().get_plugin("metrics")

        if metrics_plugin:
            metrics = metrics_plugin.get_metrics()  # type: ignore[attr-defined]
            await self.broadcast_metrics(metrics)

    async def _broadcast_health(self) -> None:
        """Broadcast health status."""
        health_plugin = get_plugin_manager().get_plugin("healthcheck")

        if health_plugin:
            health = await health_plugin.run_checks()  # type: ignore[attr-defined]
            await self.broadcast_health(health)
