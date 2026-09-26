"""
Cost Analysis & Optimization for PyFault framework.

Cost tracking and optimization:
- Resource cost tracking (compute, storage, network)
- Budget management and alerts
- Cost allocation by tenant/project
- Optimization recommendations
- Chargeback/showback reports
"""

import asyncio
import logging
import statistics
import uuid
import warnings
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    """Types of billable resources."""
    COMPUTE = "compute"          # CPU, memory, GPU
    STORAGE = "storage"          # Disk, object storage, database
    NETWORK = "network"          # Bandwidth, CDN, load balancer
    API_CALLS = "api_calls"      # API requests
    FUNCTION_INVOCATIONS = "function_invocations"  # Serverless
    DATABASE = "database"        # Database queries, connections
    CACHE = "cache"              # Redis, Memcached
    QUEUE = "queue"              # Message queues
    MONITORING = "monitoring"    # Logs, metrics, traces
    LICENSE = "license"          # Software licenses
    SUPPORT = "support"          # Support tiers
    CUSTOM = "custom"


class CostCategory(str, Enum):
    """Cost categories for allocation."""
    DIRECT = "direct"           # Directly attributable
    SHARED = "shared"           # Shared across tenants
    OVERHEAD = "overhead"       # Platform overhead
    DISCOUNT = "discount"       # Credits/discounts


class BillingPeriod(str, Enum):
    """Billing periods."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class Currency(str, Enum):
    """Supported currencies."""
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CNY = "CNY"


@dataclass
class PriceRule:
    """Pricing rule for a resource."""
    rule_id: str
    resource_type: ResourceType
    name: str
    description: str = ""

    # Pricing model
    unit: str = ""  # hour, GB, request, million_invocations, etc.
    price_per_unit: float = 0.0
    currency: Currency = Currency.USD

    # Tiered pricing
    tiers: list[dict[str, Any]] = field(default_factory=list)  # [{threshold, price_per_unit}]

    # Conditions
    conditions: dict[str, Any] = field(default_factory=dict)  # region, instance_type, etc.

    # Validity
    effective_from: datetime = field(default_factory=datetime.utcnow)
    effective_until: Optional[datetime] = None

    # Metadata
    tags: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def calculate_cost(self, usage: float, context: Optional[dict[str, Any]] = None) -> float:
        """Calculate cost for given usage."""
        if not self._matches_conditions(context or {}):
            return 0.0

        if self.tiers:
            # Tiered pricing
            cost = 0.0
            remaining = usage
            for tier in sorted(self.tiers, key=lambda t: t.get("threshold", 0)):
                threshold = tier.get("threshold", float('inf'))
                tier_price = tier.get("price_per_unit", self.price_per_unit)
                tier_usage = min(remaining, threshold)
                cost += tier_usage * tier_price
                remaining -= tier_usage
                if remaining <= 0:
                    break
            return cost
        else:
            # Flat rate
            return usage * self.price_per_unit

    def _matches_conditions(self, context: dict[str, Any]) -> bool:
        return all(context.get(key) == value for key, value in self.conditions.items())


@dataclass
class UsageRecord:
    """Record of resource usage."""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    resource_type: ResourceType = ResourceType.CUSTOM
    resource_id: str = ""  # Specific resource identifier
    resource_name: str = ""

    # Usage
    quantity: float = 0.0
    unit: str = ""

    # Time
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime = field(default_factory=datetime.utcnow)

    # Cost
    price_rule_id: str = ""
    unit_price: float = 0.0
    total_cost: float = 0.0
    currency: Currency = Currency.USD

    # Attribution
    project_id: str = ""
    environment: str = ""  # prod, staging, dev
    tags: dict[str, str] = field(default_factory=dict)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "tenant_id": self.tenant_id,
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "price_rule_id": self.price_rule_id,
            "unit_price": self.unit_price,
            "total_cost": self.total_cost,
            "currency": self.currency.value,
            "project_id": self.project_id,
            "environment": self.environment,
            "tags": self.tags,
        }


@dataclass
class Budget:
    """Budget definition and tracking."""
    budget_id: str
    name: str
    description: str = ""

    # Scope
    tenant_id: str = ""  # Empty = global
    project_id: str = ""  # Empty = all projects
    resource_types: list[ResourceType] = field(default_factory=list)  # Empty = all

    # Budget
    amount: float = 0.0
    currency: Currency = Currency.USD
    period: BillingPeriod = BillingPeriod.MONTHLY

    # Alerts
    alert_thresholds: list[float] = field(default_factory=lambda: [0.5, 0.75, 0.9, 1.0])
    alert_recipients: list[str] = field(default_factory=list)

    # Actions on threshold breach
    auto_disable: bool = False
    auto_alert: bool = True

    # Status
    active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def get_period_start(self, reference: Optional[datetime] = None) -> datetime:
        ref = reference or datetime.utcnow()
        if self.period == BillingPeriod.MONTHLY:
            return ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif self.period == BillingPeriod.WEEKLY:
            return ref - timedelta(days=ref.weekday())
        elif self.period == BillingPeriod.DAILY:
            return ref.replace(hour=0, minute=0, second=0, microsecond=0)
        elif self.period == BillingPeriod.YEARLY:
            return ref.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return ref

    def get_period_end(self, reference: Optional[datetime] = None) -> datetime:
        ref = reference or datetime.utcnow()
        start = self.get_period_start(ref)
        if self.period == BillingPeriod.MONTHLY:
            return (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(seconds=1)
        elif self.period == BillingPeriod.WEEKLY:
            return start + timedelta(days=7) - timedelta(seconds=1)
        elif self.period == BillingPeriod.DAILY:
            return start + timedelta(days=1) - timedelta(seconds=1)
        elif self.period == BillingPeriod.YEARLY:
            return start.replace(year=start.year + 1) - timedelta(seconds=1)
        return ref

    def is_in_period(self, timestamp: Optional[datetime] = None) -> bool:
        ts = timestamp or datetime.utcnow()
        start = self.get_period_start(ts)
        end = self.get_period_end(ts)
        return start <= ts <= end

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "name": self.name,
            "description": self.description,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "resource_types": [rt.value for rt in self.resource_types],
            "amount": self.amount,
            "currency": self.currency.value,
            "period": self.period.value,
            "alert_thresholds": self.alert_thresholds,
            "alert_recipients": self.alert_recipients,
            "auto_disable": self.auto_disable,
            "auto_alert": self.auto_alert,
            "active": self.active,
            "period_start": self.get_period_start().isoformat(),
            "period_end": self.get_period_end().isoformat(),
        }


@dataclass
class CostAllocation:
    """Cost allocation result."""
    allocation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    project_id: str = ""
    period_start: datetime = field(default_factory=datetime.utcnow)
    period_end: datetime = field(default_factory=datetime.utcnow)

    # Costs by resource type
    costs_by_type: dict[ResourceType, float] = field(default_factory=dict)
    costs_by_category: dict[CostCategory, float] = field(default_factory=dict)
    costs_by_project: dict[str, float] = field(default_factory=dict)
    costs_by_environment: dict[str, float] = field(default_factory=dict)
    costs_by_tag: dict[str, float] = field(default_factory=dict)

    # Totals
    total_cost: float = 0.0
    currency: Currency = Currency.USD

    # Details
    record_count: int = 0
    details: list[UsageRecord] = field(default_factory=list)

    # Metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "costs_by_type": {k.value: v for k, v in self.costs_by_type.items()},
            "costs_by_category": {k.value: v for k, v in self.costs_by_category.items()},
            "costs_by_project": self.costs_by_project,
            "costs_by_environment": self.costs_by_environment,
            "costs_by_tag": self.costs_by_tag,
            "total_cost": self.total_cost,
            "currency": self.currency.value,
            "record_count": self.record_count,
        }


@dataclass
class CostOptimizationRecommendation:
    """Cost optimization recommendation."""
    recommendation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    category: str = ""  # rightsizing, scheduling, storage, network, etc.

    # Impact
    estimated_monthly_savings: float = 0.0
    currency: Currency = Currency.USD
    confidence: float = 0.0  # 0-1

    # Effort
    effort_level: str = "low"  # low, medium, high
    implementation_time_hours: float = 0

    # Details
    affected_resources: list[str] = field(default_factory=list)
    current_cost: float = 0.0
    projected_cost: float = 0.0
    reasoning: str = ""

    # Action
    action_required: str = ""
    automation_possible: bool = False
    rollback_possible: bool = True

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "estimated_monthly_savings": self.estimated_monthly_savings,
            "currency": self.currency.value,
            "confidence": self.confidence,
            "effort_level": self.effort_level,
            "implementation_time_hours": self.implementation_time_hours,
            "affected_resources": self.affected_resources,
            "current_cost": self.current_cost,
            "projected_cost": self.projected_cost,
            "reasoning": self.reasoning,
            "action_required": self.action_required,
            "automation_possible": self.automation_possible,
            "rollback_possible": self.rollback_possible,
        }


class CostTracker:
    """Tracks resource usage and costs."""

    def __init__(self) -> None:
        self._price_rules: dict[str, PriceRule] = {}
        self._usage_records: deque = deque(maxlen=1000000)
        self._budgets: dict[str, Budget] = {}
        self._allocations: dict[str, CostAllocation] = {}
        self._recommendations: list[CostOptimizationRecommendation] = []
        self._running = False
        self._collection_task: Optional[asyncio.Task] = None

    def add_price_rule(self, rule: PriceRule) -> None:
        self._price_rules[rule.rule_id] = rule

    def remove_price_rule(self, rule_id: str) -> bool:
        if rule_id in self._price_rules:
            del self._price_rules[rule_id]
            return True
        return False

    def get_price_rule(self, rule_id: str) -> Optional[PriceRule]:
        return self._price_rules.get(rule_id)

    def list_price_rules(self, resource_type: Optional[ResourceType] = None) -> list[PriceRule]:
        rules = list(self._price_rules.values())
        if resource_type:
            rules = [r for r in rules if r.resource_type == resource_type]
        return rules

    async def record_usage(self, record: UsageRecord) -> bool:
        """Record a usage event and calculate cost."""
        # Find matching price rule
        matching_rules = [
            r for r in self._price_rules.values()
            if r.resource_type == record.resource_type and r._matches_conditions(record.metadata)
        ]

        if not matching_rules:
            logger.warning(f"No price rule found for {record.resource_type}")
            return False

        # Use the best matching rule (most specific)
        rule = max(matching_rules, key=lambda r: len(r.conditions))

        record.price_rule_id = rule.rule_id
        record.unit_price = rule.price_per_unit
        record.total_cost = rule.calculate_cost(record.quantity, record.metadata)
        record.currency = rule.currency

        self._usage_records.append(record)

        # Check budgets
        await self._check_budgets(record)

        return True

    async def record_batch_usage(self, records: list[UsageRecord]) -> int:
        count = 0
        for record in records:
            if await self.record_usage(record):
                count += 1
        return count

    async def _check_budgets(self, record: UsageRecord) -> None:
        for budget in self._budgets.values():
            if not budget.active or not budget.is_in_period(record.end_time):
                continue

            # Check scope
            if budget.tenant_id and budget.tenant_id != record.tenant_id:
                continue
            if budget.project_id and budget.project_id != record.project_id:
                continue
            if budget.resource_types and record.resource_type not in budget.resource_types:
                continue

            # Calculate current spend in period
            period_start = budget.get_period_start(record.end_time)
            period_end = budget.get_period_end(record.end_time)

            period_spend = sum(
                r.total_cost for r in self._usage_records
                if r.tenant_id == record.tenant_id
                and (not budget.project_id or r.project_id == budget.project_id)
                and (not budget.resource_types or r.resource_type in budget.resource_types)
                and period_start <= r.end_time <= period_end
            )

            # Check thresholds
            utilization = period_spend / budget.amount if budget.amount > 0 else 0

            for threshold in budget.alert_thresholds:
                if utilization >= threshold:
                    # Check if already alerted for this threshold
                    # In production, would track alerted thresholds
                    logger.warning(f"Budget {budget.name} at {utilization:.1%} utilization (threshold: {threshold:.0%})")

                    if budget.auto_alert:
                        # Send alert (would integrate with notification system)
                        pass

                    if budget.auto_disable and utilization >= 1.0:
                        logger.critical(f"Budget {budget.name} exceeded! Auto-disabling resources.")

    def create_budget(self, budget: Budget) -> None:
        self._budgets[budget.budget_id] = budget

    def get_budget(self, budget_id: str) -> Optional[Budget]:
        return self._budgets.get(budget_id)

    def list_budgets(self, tenant_id: Optional[str] = None) -> list[Budget]:
        budgets = list(self._budgets.values())
        if tenant_id:
            budgets = [b for b in budgets if b.tenant_id == tenant_id]
        return budgets

    def allocate_costs(
        self,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> CostAllocation:
        """Allocate costs for a period."""
        start = start_time or (datetime.utcnow() - timedelta(days=30))
        end = end_time or datetime.utcnow()

        allocation = CostAllocation(
            tenant_id=tenant_id or "",
            project_id=project_id or "",
            period_start=start,
            period_end=end,
        )

        for record in self._usage_records:
            if record.end_time < start or record.end_time > end:
                continue
            if tenant_id and record.tenant_id != tenant_id:
                continue
            if project_id and record.project_id != project_id:
                continue

            allocation.costs_by_type[record.resource_type] = (
                allocation.costs_by_type.get(record.resource_type, 0) + record.total_cost
            )

            # Categorize
            category = self._categorize_resource(record.resource_type)
            allocation.costs_by_category[category] = (
                allocation.costs_by_category.get(category, 0) + record.total_cost
            )

            if record.project_id:
                allocation.costs_by_project[record.project_id] = (
                    allocation.costs_by_project.get(record.project_id, 0) + record.total_cost
                )

            if record.environment:
                allocation.costs_by_environment[record.environment] = (
                    allocation.costs_by_environment.get(record.environment, 0) + record.total_cost
                )

            for tag, value in record.tags.items():
                tag_key = f"{tag}:{value}"
                allocation.costs_by_tag[tag_key] = (
                    allocation.costs_by_tag.get(tag_key, 0) + record.total_cost
                )

            allocation.total_cost += record.total_cost
            allocation.record_count += 1
            allocation.details.append(record)

        allocation.currency = Currency.USD
        return allocation

    def _categorize_resource(self, resource_type: ResourceType) -> CostCategory:
        """Categorize resource type into cost category."""
        direct_types = {
            ResourceType.COMPUTE, ResourceType.STORAGE, ResourceType.DATABASE,
            ResourceType.FUNCTION_INVOCATIONS, ResourceType.API_CALLS,
        }
        shared_types = {
            ResourceType.NETWORK, ResourceType.CACHE, ResourceType.QUEUE,
            ResourceType.MONITORING, ResourceType.SUPPORT,
        }

        if resource_type in direct_types:
            return CostCategory.DIRECT
        elif resource_type in shared_types:
            return CostCategory.SHARED
        else:
            return CostCategory.OVERHEAD

    def generate_recommendations(self) -> list[CostOptimizationRecommendation]:
        """Generate cost optimization recommendations."""
        recommendations = []

        # Analyze usage patterns for rightsizing
        compute_usage = [
            r for r in self._usage_records
            if r.resource_type == ResourceType.COMPUTE
        ]

        if compute_usage:
            # Group by resource_id
            by_resource = defaultdict(list)
            for r in compute_usage:
                by_resource[r.resource_id].append(r)

            for resource_id, records in by_resource.items():
                avg_usage = statistics.mean(r.quantity for r in records) if records else 0
                max_usage = max(r.quantity for r in records) if records else 0

                # Low utilization - suggest downsizing
                if avg_usage < 0.3 and max_usage < 0.5:
                    current_cost = sum(r.total_cost for r in records)
                    savings = current_cost * 0.5  # Estimate 50% savings

                    recommendations.append(CostOptimizationRecommendation(
                        title=f"Downsize compute resource {resource_id}",
                        description=f"Resource {resource_id} has low CPU utilization ({avg_usage:.1%} avg, {max_usage:.1%} max). Consider downsizing.",
                        category="rightsizing",
                        estimated_monthly_savings=savings,
                        confidence=0.8,
                        effort_level="low",
                        implementation_time_hours=2,
                        affected_resources=[resource_id],
                        current_cost=current_cost,
                        projected_cost=current_cost * 0.5,
                        reasoning="Consistently low utilization indicates over-provisioning",
                        action_required="Downsize instance type or use auto-scaling",
                        automation_possible=True,
                    ))

        # Storage optimization
        storage_usage = [
            r for r in self._usage_records
            if r.resource_type == ResourceType.STORAGE
        ]

        if storage_usage:
            # Check for old/unaccessed data
            old_data = [
                r for r in storage_usage
                if r.metadata.get("last_accessed_days", 0) > 90
            ]

            if old_data:
                old_cost = sum(r.total_cost for r in old_data)
                recommendations.append(CostOptimizationRecommendation(
                    title="Enable tiered storage for cold data",
                    description=f"Found {len(old_data)} storage resources not accessed in 90+ days",
                    category="storage_tiering",
                    estimated_monthly_savings=old_cost * 0.6,  # 60% savings on cold storage
                    confidence=0.9,
                    effort_level="low",
                    implementation_time_hours=1,
                    affected_resources=[r.resource_id for r in old_data],
                    current_cost=old_cost,
                    projected_cost=old_cost * 0.4,
                    reasoning="Cold data can be moved to cheaper storage tier",
                    action_required="Configure lifecycle policies for tiered storage",
                    automation_possible=True,
                ))

        # Idle resource detection
        idle_resources = self._find_idle_resources()
        if idle_resources:
            idle_cost = sum(r.total_cost for r in idle_resources)
            recommendations.append(CostOptimizationRecommendation(
                title="Terminate idle resources",
                description=f"Found {len(idle_resources)} resources with no activity in 7+ days",
                category="idle_resources",
                estimated_monthly_savings=idle_cost,
                confidence=0.95,
                effort_level="low",
                implementation_time_hours=0.5,
                affected_resources=[r.resource_id for r in idle_resources],
                current_cost=idle_cost,
                projected_cost=0,
                reasoning="Resources with no activity for extended period",
                action_required="Terminate or schedule shutdown",
                automation_possible=True,
            ))

        # Reserved instances / Savings plans
        on_demand_compute = [
            r for r in self._usage_records
            if r.resource_type == ResourceType.COMPUTE and r.metadata.get("pricing_model") == "on_demand"
        ]

        if on_demand_compute:
            on_demand_cost = sum(r.total_cost for r in on_demand_compute)
            steady_usage = self._check_steady_usage(on_demand_compute)

            if steady_usage > 0.7:  # 70%+ steady
                recommendations.append(CostOptimizationRecommendation(
                    title="Purchase reserved instances / savings plans",
                    description=f"Steady compute usage ({steady_usage:.0%}) qualifies for reserved pricing",
                    category="reserved_instances",
                    estimated_monthly_savings=on_demand_cost * 0.3,  # ~30% savings
                    confidence=0.85,
                    effort_level="medium",
                    implementation_time_hours=4,
                    affected_resources=[r.resource_id for r in on_demand_compute],
                    current_cost=on_demand_cost,
                    projected_cost=on_demand_cost * 0.7,
                    reasoning="Steady usage pattern qualifies for reserved pricing discounts",
                    action_required="Purchase 1-year or 3-year reserved instances",
                    automation_possible=True,
                ))

        self._recommendations = recommendations
        return recommendations

    def _find_idle_resources(self, idle_days: int = 7) -> list[UsageRecord]:
        """Find resources with no activity."""
        cutoff = datetime.utcnow() - timedelta(days=idle_days)

        # Group by resource
        by_resource = defaultdict(list)
        for r in self._usage_records:
            if r.end_time > cutoff:
                return []  # Has recent activity
            by_resource[r.resource_id].append(r)

        idle = []
        for _resource_id, records in by_resource.items():
            latest = max(r.end_time for r in records)
            if latest < cutoff:
                idle.append(records[-1])  # Latest record

        return idle

    def _check_steady_usage(self, records: list[UsageRecord]) -> float:
        """Check if usage is steady over time."""
        if len(records) < 7:  # Need at least a week
            return 0.0

        daily_costs: dict[date, float] = defaultdict(float)
        for r in records:
            day = r.end_time.date()
            daily_costs[day] += r.total_cost

        if len(daily_costs) < 7:
            return 0.0

        costs = list(daily_costs.values())
        mean = statistics.mean(costs)
        stdev = statistics.stdev(costs) if len(costs) > 1 else 0

        # Coefficient of variation
        cv = stdev / mean if mean > 0 else 1.0

        # Low CV = steady usage
        return max(0, 1 - cv)


class CostReporter:
    """Generates cost reports."""

    def __init__(self, tracker: CostTracker):
        self.tracker = tracker

    async def generate_monthly_report(
        self,
        tenant_id: Optional[str] = None,
        month: Optional[datetime] = None,
    ) -> dict[str, Any]:
        month = month or datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(seconds=1)

        allocation = self.tracker.allocate_costs(tenant_id=tenant_id, start_time=month, end_time=end)
        recommendations = self.tracker.generate_recommendations()

        return {
            "report_type": "Monthly Cost Report",
            "period": {"start": month.isoformat(), "end": end.isoformat()},
            "tenant_id": tenant_id,
            "summary": {
                "total_cost": allocation.total_cost,
                "currency": allocation.currency.value,
                "record_count": allocation.record_count,
            },
            "by_resource_type": {
                k.value: v for k, v in allocation.costs_by_type.items()
            },
            "by_category": {
                k.value: v for k, v in allocation.costs_by_category.items()
            },
            "by_project": allocation.costs_by_project,
            "by_environment": allocation.costs_by_environment,
            "by_tag": allocation.costs_by_tag,
            "recommendations": [r.to_dict() for r in recommendations],
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def generate_budget_report(self, budget_id: str) -> dict[str, Any]:
        budget = self.tracker.get_budget(budget_id)
        if not budget:
            return {"error": "Budget not found"}

        period_start = budget.get_period_start()
        period_end = budget.get_period_end()

        allocation = self.tracker.allocate_costs(
            tenant_id=budget.tenant_id,
            project_id=budget.project_id,
            start_time=period_start,
            end_time=period_end,
        )

        utilization = allocation.total_cost / budget.amount if budget.amount > 0 else 0

        return {
            "budget": budget.to_dict(),
            "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
            "spent": allocation.total_cost,
            "budget_amount": budget.amount,
            "utilization": utilization,
            "remaining": max(0, budget.amount - allocation.total_cost),
            "status": "over" if utilization > 1.0 else "under" if utilization < 1.0 else "on_track",
            "by_resource": {k.value: v for k, v in allocation.costs_by_type.items()},
            "alerts_triggered": [t for t in budget.alert_thresholds if utilization >= t],
        }

    async def generate_chargeback_report(
        self,
        tenant_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """Generate chargeback/showback report for a tenant."""
        allocation = self.tracker.allocate_costs(
            tenant_id=tenant_id,
            start_time=start_time,
            end_time=end_time,
        )

        # Break down by project
        project_details = {}
        for project_id, cost in allocation.costs_by_project.items():
            proj_allocation = self.tracker.allocate_costs(
                tenant_id=tenant_id,
                project_id=project_id,
                start_time=start_time,
                end_time=end_time,
            )
            project_details[project_id] = {
                "total_cost": cost,
                "by_type": {k.value: v for k, v in proj_allocation.costs_by_type.items()},
                "by_category": {k.value: v for k, v in proj_allocation.costs_by_category.items()},
            }

        return {
            "report_type": "Chargeback Report",
            "tenant_id": tenant_id,
            "period": {"start": start_time.isoformat(), "end": end_time.isoformat()},
            "total_cost": allocation.total_cost,
            "currency": allocation.currency.value,
            "project_breakdown": project_details,
            "by_environment": allocation.costs_by_environment,
            "by_category": {k.value: v for k, v in allocation.costs_by_category.items()},
            "generated_at": datetime.utcnow().isoformat(),
        }


class CostOptimizer:
    """Automated cost optimization."""

    def __init__(self, tracker: CostTracker):
        self.tracker = tracker
        self._rules: list[Callable] = []

    def add_optimization_rule(self, rule: Callable) -> None:
        self._rules.append(rule)

    async def run_optimization(self, dry_run: bool = True) -> list[dict[str, Any]]:
        """Run all optimization rules."""
        recommendations = self.tracker.generate_recommendations()
        results = []

        for rec in recommendations:
            result = {
                "recommendation": rec.to_dict(),
                "applied": False,
                "dry_run": dry_run,
            }

            if not dry_run and rec.automation_possible:
                try:
                    await self._apply_recommendation(rec)
                    result["applied"] = True
                except Exception as e:
                    result["error"] = str(e)

            results.append(result)

        return results

    async def _apply_recommendation(self, rec: CostOptimizationRecommendation) -> bool:
        # In production, would integrate with cloud provider APIs
        logger.info(f"Applying recommendation: {rec.title}")
        return True


# Global instances
_cost_tracker: Optional[CostTracker] = None
_cost_reporter: Optional[CostReporter] = None
_cost_optimizer: Optional[CostOptimizer] = None


def get_cost_tracker() -> CostTracker:
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker


def get_cost_reporter() -> CostReporter:
    global _cost_reporter
    if _cost_reporter is None:
        _cost_reporter = CostReporter(get_cost_tracker())
    return _cost_reporter


def get_cost_optimizer() -> CostOptimizer:
    global _cost_optimizer
    if _cost_optimizer is None:
        _cost_optimizer = CostOptimizer(get_cost_tracker())
    return _cost_optimizer


# Aliases for backward compatibility
get_cost_tracker = get_cost_tracker
get_cost_reporter = get_cost_reporter
get_cost_optimizer = get_cost_optimizer


__all__ = [
    "ResourceType",
    "CostCategory",
    "BillingPeriod",
    "Currency",
    "PriceRule",
    "UsageRecord",
    "Budget",
    "CostAllocation",
    "CostOptimizationRecommendation",
    "CostTracker",
    "CostReporter",
    "CostOptimizer",
    "get_cost_tracker",
    "get_cost_reporter",
    "get_cost_optimizer",
]
