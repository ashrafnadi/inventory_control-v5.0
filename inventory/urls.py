# inventory/urls.py
from django.urls import path

from . import views

urlpatterns = [
    path("transactions/", views.transaction_list_view, name="transaction_list"),
    path(
        "transactions/pending/",
        views.pending_transactions_list,
        name="pending_transactions",
    ),
    path(
        "transactions/new/",
        views.transaction_create_disbursement_view,
        name="transaction_create",
    ),
    path(
        "transactions/add/",
        views.transaction_create_addition_view,
        name="transaction_create_addition",
    ),
    path(
        "transactions/transfer/",
        views.transaction_create_transfer_view,
        name="transaction_create_transfer",
    ),
    path(
        "transactions/return/",
        views.transaction_create_return_view,
        name="transaction_create_return",
    ),
    path(
        "transactions/<int:pk>/",
        views.transaction_detail_view,
        name="transaction_detail",
    ),
    path(
        "transactions/approve/<int:pk>/",
        views.transaction_approve_view,
        name="transaction_approve",
    ),
    path(
        "transactions/reject/<int:pk>/",
        views.transaction_reject_view,
        name="transaction_reject",
    ),
    path(
        "transactions/edit/<int:transaction_id>/",
        views.transaction_edit_view,
        name="transaction_edit",
    ),
    path(
        "transactions/edit/addition/<int:transaction_id>/",
        views.transaction_edit_addition_view,
        name="transaction_edit_addition",
    ),
    path(
        "transactions/edit/disbursement/<int:transaction_id>/",
        views.transaction_edit_disbursement_view,
        name="transaction_edit_disbursement",
    ),
    path(
        "transactions/edit/transfer/<int:transaction_id>/",
        views.transaction_edit_transfer_view,
        name="transaction_edit_transfer",
    ),
    path(
        "transactions/edit/return/<int:transaction_id>/",
        views.transaction_edit_return_view,
        name="transaction_edit_return",
    ),
    path(
        "transactions/delete/<int:transaction_id>/",
        views.transaction_delete_view,
        name="transaction_delete",
    ),
    path(
        "transactions/audit/<int:transaction_id>/",
        views.transaction_audit_log_view,
        name="transaction_audit_log",
    ),
    path(
        "transactions/<int:transaction_id>/pdf/",
        views.export_transaction_pdf,
        name="export_transaction_pdf",
    ),
    path(
        "transactions/<int:transaction_id>/reverse/",
        views.transaction_reverse_view,
        name="transaction_reverse",
    ),
    path(
        "htmx/inventory-users/",
        views.inventory_user_select,
        name="inventory_user_select",
    ),
    path(
        "htmx/inventory-users/addition/",
        views.inventory_user_select_addition,
        name="inventory_user_select_addition",
    ),
    path(
        "htmx/inventory-users/return/",
        views.inventory_user_select_return,
        name="inventory_user_select_return",
    ),
    path(
        "htmx/department-users/",
        views.department_users_select,
        name="department_users_select",
    ),
    path(
        "htmx/department-users/return/",
        views.from_department_users_select_return,
        name="from_department_users_select_return",
    ),
    path(
        "htmx/categories/",
        views.categories_by_warehouse,
        name="categories_by_warehouse",
    ),
    path("htmx/items/", views.items_by_category, name="items_by_category"),
    path(
        "htmx/transfer/from-sub-warehouse-users/",
        views.from_sub_warehouse_users_select_transfer,
        name="from_sub_warehouse_users_select_transfer",
    ),
    path(
        "htmx/transfer/to-sub-warehouse-users/",
        views.to_sub_warehouse_users_select_transfer,
        name="to_sub_warehouse_users_select_transfer",
    ),
    path(
        "htmx/transfer/from-department-users/",
        views.from_department_users_select_transfer,
        name="from_department_users_select_transfer",
    ),
    path(
        "htmx/transfer/to-department-users/",
        views.to_department_users_select_transfer,
        name="to_department_users_select_transfer",
    ),
    path("api/item-search/", views.item_search_ajax, name="item_search"),
    path(
        "api/item-search/addition/",
        views.item_search_addition,
        name="item_search_addition",
    ),
    path(
        "api/item-search/transfer/",
        views.item_search_transfer,
        name="item_search_transfer",
    ),
    path(
        "api/item-search/return/", views.item_search_return, name="item_search_return"
    ),
    path("api/item-name/", views.get_item_name, name="get_item_name"),
    path(
        "api/items-by-warehouse-category/",
        views.items_by_warehouse_and_category,
        name="items_by_warehouse_and_category",
    ),
    path("inventory/", views.warehouse_inventory_view, name="warehouse_inventory"),
    path(
        "inventory/all-faculties/", views.admin_all_items_view, name="admin_all_items"
    ),
    path("items/", views.item_list, name="item_list"),
    path("items/create/", views.item_create, name="item_create"),
    path("items/<int:item_id>/edit/", views.item_edit, name="item_edit"),
    path("items/<int:item_id>/delete/", views.item_delete, name="item_delete"),
    path("item/<int:item_id>/history/", views.item_history_view, name="item_history"),
    path(
        "htmx/categories-by-subwarehouse/",
        views.categories_by_subwarehouse,
        name="categories_by_subwarehouse",
    ),
    path(
        "items/<int:item_id>/history/pdf/",
        views.item_history_pdf,
        name="item_history_pdf",
    ),
    path(
        "export/item-history/excel/<int:item_id>/",
        views.item_history_xlsx,
        name="item_history_xlsx",
    ),
    path("warehouses/", views.warehouse_list, name="warehouse_list"),
    path("warehouses/create/", views.warehouse_create, name="warehouse_create"),
    path("warehouses/<int:pk>/edit/", views.warehouse_update, name="warehouse_update"),
    path(
        "warehouses/<int:pk>/delete/", views.warehouse_delete, name="warehouse_delete"
    ),
    path("categories/", views.itemcategory_list, name="itemcategory_list"),
    path("categories/create/", views.itemcategory_create, name="itemcategory_create"),
    path(
        "categories/<int:pk>/edit/",
        views.itemcategory_update,
        name="itemcategory_update",
    ),
    path(
        "categories/<int:pk>/delete/",
        views.itemcategory_delete,
        name="itemcategory_delete",
    ),
    path("sub-warehouses/", views.subwarehouse_list, name="subwarehouse_list"),
    path(
        "sub-warehouses/create/", views.subwarehouse_create, name="subwarehouse_create"
    ),
    path(
        "sub-warehouses/<int:pk>/edit/",
        views.subwarehouse_update,
        name="subwarehouse_update",
    ),
    path(
        "sub-warehouses/<int:pk>/delete/",
        views.subwarehouse_delete,
        name="subwarehouse_delete",
    ),
    path("custody/", views.employee_custody_view, name="employee_custody"),
    path(
        "custody/export/excel/<int:employee_id>/",
        views.export_employee_custody_excel,
        name="export_employee_custody_excel",
    ),
    path(
        "custody/export/pdf/<int:employee_id>/",
        views.export_employee_custody_pdf,
        name="export_employee_custody_pdf",
    ),
    path(
        "custody/export/department/pdf/<int:department_id>/",
        views.export_department_custody_pdf,
        name="export_department_custody_pdf",
    ),
    path(
        "custody/department-employees/",
        views.department_employees_for_custody,
        name="department_employees_for_custody",
    ),
    path("suppliers/", views.supplier_list_view, name="supplier_list"),
    path("suppliers/create/", views.supplier_create_view, name="supplier_create"),
    path("suppliers/<int:pk>/", views.supplier_detail_view, name="supplier_detail"),
    path(
        "suppliers/<int:pk>/update/", views.supplier_update_view, name="supplier_update"
    ),
    path(
        "suppliers/<int:pk>/delete/", views.supplier_delete_view, name="supplier_delete"
    ),
    path(
        "export/inventory/excel/",
        views.export_inventory_excel,
        name="export_inventory_excel",
    ),
    path(
        "export/inventory/pdf/", views.export_inventory_pdf, name="export_inventory_pdf"
    ),
    path(
        "items/check-code/",
        views.check_item_code_availability,
        name="check_item_code_availability",
    ),
    path(
        "items/api/",
        views.item_list_api,  # Make sure this function exists in views.py
        name="item_list_api",
    ),
    path(
        "admin/transactions/",
        views.admin_transaction_list,
        name="admin_transaction_list",
    ),
    path(
        "admin/transactions/<int:transaction_id>/",
        views.admin_transaction_detail,
        name="admin_transaction_detail",
    ),
    path(
        "admin/transactions/<int:transaction_id>/update-prices/",
        views.admin_update_transaction_prices,
        name="admin_update_transaction_prices",
    ),
    path(
        "admin/faculty-stock/",
        views.admin_faculty_stock_view,
        name="admin_faculty_stock_view",
    ),
    path(
        "items/<int:item_id>/price-history/",
        views.get_item_price_history,
        name="get_item_price_history",
    ),
    path(
        "admin/custody/edit-prices/",
        views.admin_edit_custody_prices,
        name="admin_edit_custody_prices",
    ),
    path(
        "admin/custody/load-departments/",
        views.htmx_load_departments,
        name="htmx_load_departments",
    ),
    path(
        "admin/custody/load-employees/",
        views.htmx_load_employees,
        name="htmx_load_employees",
    ),
    path(
        "admin/transactions/<int:transaction_id>/edit/",
        views.admin_edit_transaction_header,
        name="admin_edit_transaction",
    ),
    path(
        "admin/faculty-items/",
        views.admin_faculty_items_view,
        name="admin_faculty_items",
    ),
    path(
        "admin/faculty-items/load/",
        views.htmx_load_faculty_items,
        name="htmx_load_faculty_items",
    ),
    path(
        "admin/item-history/<int:item_id>/",
        views.admin_item_transaction_history,
        name="admin_item_transaction_history",
    ),
]
