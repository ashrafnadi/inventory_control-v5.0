from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="home"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("profile/", views.profile, name="profile"),
    path(
        "export-low-stock-items-pdf/",
        views.export_low_stock_items_pdf,
        name="export_low_stock_items_pdf",
    ),
    path(
        "export-users-roles-report/",
        views.export_users_roles_report,
        name="export_users_roles_report",
    ),
    path("charts-data/", views.admin_charts_data, name="admin_charts_data"),
    path("departments/", views.department_list, name="department_list"),
    path("departments/create/", views.department_create, name="department_create"),
    path(
        "departments/<int:department_id>/edit/",
        views.department_edit,
        name="department_edit",
    ),
    path(
        "departments/<int:department_id>/delete/",
        views.department_delete,
        name="department_delete",
    ),
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/create/", views.employee_create, name="employee_create"),
    path(
        "employees/<int:employee_id>/edit/", views.employee_edit, name="employee_edit"
    ),
    path("password-change/", views.password_change_view, name="password_change"),
    path("settings/system/", views.system_settings, name="system_settings"),
    path(
        "settings/years/<int:year_id>/close/",
        views.close_inventory_year,
        name="close_inventory_year",
    ),
    path(
        "api/subwarehouse-charts/<int:subwarehouse_id>/",
        views.get_subwarehouse_charts,
        name="subwarehouse_charts",
    ),
    path(
        "api/subwarehouse-charts/<int:subwarehouse_id>/json/",
        views.get_subwarehouse_charts_api,
        name="subwarehouse_charts_api",
    ),
    # ADMINISTRATION MANAGER
    path(
        "administration/item-search/",
        views.administration_item_search,
        name="administration_item_search",
    ),
    path(
        "administration/item-search/api/",
        views.administration_item_search_api,
        name="administration_item_search_api",
    ),
    # Users
    path("users/", views.admin_user_list, name="admin_user_list"),
    path("users/create/", views.admin_user_create, name="admin_user_create"),
    path("users/<int:user_id>/edit/", views.admin_user_edit, name="admin_user_edit"),
    path(
        "users/<int:user_id>/delete/", views.admin_user_delete, name="admin_user_delete"
    ),
    # Faculties
    path("faculties/", views.admin_faculty_list, name="admin_faculty_list"),
    path("faculties/create/", views.admin_faculty_create, name="admin_faculty_create"),
    path(
        "faculties/<int:faculty_id>/edit/",
        views.admin_faculty_edit,
        name="admin_faculty_edit",
    ),
    path(
        "api/departments/by-faculty/",
        views.get_departments_by_faculty,
        name="api_departments_by_faculty",
    ),
    path(
        "faculties/<int:faculty_id>/delete/",
        views.admin_faculty_delete,
        name="admin_faculty_delete",
    ),
    path(
        "users/import-excel/",
        views.admin_user_import_excel,
        name="admin_user_import_excel",
    ),
    # Departments
    path(
        "faculties/departments/",
        views.admin_department_list,
        name="admin_department_list",
    ),
    path(
        "faculties/departments/create/",
        views.admin_department_create,
        name="admin_department_create",
    ),
    path(
        "faculties/departments/<int:dept_id>/edit/",
        views.admin_department_edit,
        name="admin_department_edit",
    ),
    path(
        "faculties/departments/<int:dept_id>/delete/",
        views.admin_department_delete,
        name="admin_department_delete",
    ),
    path("logs/", views.view_logs, name="view_logs"),
    path("backup-db/", views.admin_backup_db, name="admin_backup_db"),
]
