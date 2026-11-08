"""Sol menüdeki sayfalar: adres ve sayfa başlığı (dev-admin.easyalert.io keşfiyle çıkarıldı)."""
from pages.base_page import BasePage


def _page(name: str, path: str, heading: str) -> type[BasePage]:
    return type(name, (BasePage,), {"path": path, "heading_text": heading})


DashboardPage = _page("DashboardPage", "/dashboard", "Incident Management")
IncidentsPage = _page("IncidentsPage", "/incidents", "Incidents")
PostmortemsPage = _page("PostmortemsPage", "/postmortems", "Postmortems")
SyntheticsPage = _page("SyntheticsPage", "/synthetics", "Synthetics")
TeamsPage = _page("TeamsPage", "/teams", "Teams")
SchedulesPage = _page("SchedulesPage", "/schedules", "On-Call Schedules")
EscalationPoliciesPage = _page("EscalationPoliciesPage", "/escalation-policies", "Escalation Policies")
IntegrationsPage = _page("IntegrationsPage", "/integrations", "Integrations")
AlertRulesPage = _page("AlertRulesPage", "/alert-rules", "Alert Rules")
EscalationRoutingPage = _page("EscalationRoutingPage", "/escalation-routing", "Escalation Routing")
SettingsPage = _page("SettingsPage", "/settings", "Settings")
UsersPage = _page("UsersPage", "/iam/users", "Users")
GroupsPage = _page("GroupsPage", "/iam/groups", "Groups")
RolesPage = _page("RolesPage", "/iam/roles", "Roles")
OrganizationPage = _page("OrganizationPage", "/organization", "Organization")
UsagePage = _page("UsagePage", "/usage", "Usage & Billing")
SubscriptionPage = _page("SubscriptionPage", "/subscription", "Subscription")

SIDEBAR_PAGES = [
    DashboardPage, IncidentsPage, PostmortemsPage, SyntheticsPage, TeamsPage, SchedulesPage,
    EscalationPoliciesPage, IntegrationsPage, AlertRulesPage, EscalationRoutingPage, SettingsPage,
    UsersPage, GroupsPage, RolesPage, OrganizationPage, UsagePage, SubscriptionPage,
]
