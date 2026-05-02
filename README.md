# Inventory Control System (نظام إدارة المخازن)

## University Inventory Management System | نظام إدارة المخازن الجامعي

A robust, Django-based web application designed to manage inventory and warehouse operations efficiently. Built for Benha University (GSCC), this system handles the complete lifecycle of items from addition to disbursement, transfer, and reporting.

## 🌟 Features

### 📦 Inventory & Asset Lifecycle

* **Comprehensive Asset Tracking**: Detailed item profiles with categorization, units of measurement, and real-time automated stock calculations.
* **Transaction Workflows**:
  * **Additions (إضافة)**: Streamlined recording of new stock entry from suppliers or departmental returns.
  * **Disbursements (صرف)**: Precise management of stock allocation to departments or individuals.
  * **Transfers (نقل عهدة)**: Secure movement of items between warehouses or departments with full accountability.
  * **Returns (ارتجاع)**: Efficient processing of items being returned to central storage.
* **Multi-tier Warehouse Management**: Hierarchical structure support for Main Warehouses, Sub-warehouses, and Branch locations.
* **Diverse Custody Models**: Manage assets across different custody types: **Warehouse**, **Personal**, and **Branch** custody.
* **Transaction Reversals**: Built-in mechanism to "reverse" transactions for error correction while maintaining a clean audit trail.

### 🔐 Security & Governance

* **Fine-grained RBAC**: Layered access control for Inventory Managers, Employees, and Administrative staff, isolated by Faculty/Department.
* **Audit Logging & Compliance**: Detailed tracking of every transaction, including:
  * **Snapshots**: Full JSON snapshots of transactions at each stage.
  * **User Tracking**: Records of who performed, approved, or deleted transactions.
  * **Network Metadata**: Logging of IP addresses and user agents for security audits.
* **Document Management**: Automated generation of sequential document numbers (ADD, DIS, TRF, RET) scoped to specific warehouses.
* **Centralized Administration**: Dedicated CRUD panels for Faculty, Department, and User management, featuring bulk Excel import functionality and rigorous data integrity safeguards like dependency checks before deletion.

### 📊 Intelligence & UX

* **Interactive Dashboards**: Role-specific dashboards (Admin, Faculty Manager, Inventory Manager) providing real-time insights and data visualization.
* **Advanced Reporting**: High-fidelity export capabilities:
  * **PDF Export**: Professional reports generated via WeasyPrint/ReportLab for item history, low stock, and user roles.
  * **Excel Export**: Detailed data exports using OpenPyXL for inventory lists and transaction logs.
* **Stock Monitoring**: Automated "Low Stock" and "Out of Stock" alerts.
* **Localized Interface**: Deep localization for Arabic (ar-EG) environments, ensuring seamless operation for local administrative staff.
* **Dynamic Interactions**: Powered by HTMX for a modern, responsive single-page feel without full page reloads, complemented by standardized and visually consistent DataTables.

### ⚡ Performance & Optimization

* **Zero N+1 Queries**: Optimized database interactions preventing performance bottlenecks in complex reporting views.
* **Cached Stock Quantities**: High-performance real-time stock tracking using denormalized cached quantities.
* **Authoritative Synchronization**: Advanced global stock calculation and synchronization protocols ensuring uncompromised data integrity.

## 🛠️ Technology Stack

* **Backend**: Python 3.13+, Django 6.0
* **Database**: SQLite (Development) / PostgreSQL (Production)
* **Frontend**:
  * **Bootstrap 5**: Modern, responsive UI components.
  * **HTMX**: Dynamic content updates and high-performance user interactions.
  * **Crispy Forms**: Beautifully rendered and highly functional Django forms.
* **Reporting & Utils**:
  * **WeasyPrint & ReportLab**: Professional PDF generation.
  * **OpenPyXL**: Excel report generation and data export.
  * **WhiteNoise**: Efficient static file serving.
  * **Ruff**: Modern Python linting and formatting.
  * **Django Extensions & Debug Toolbar**: Advanced development and profiling tools.
  * **Pillow**: Image processing for item profiles.

## 🚀 Getting Started

### Prerequisites

* Python 3.13 or higher
* [uv](https://github.com/astral-sh/uv) (recommended) or pip
* **System Libraries**: For PDF generation (WeasyPrint), you may need: `libmagic`, `pango`, `cairo`, `gdk-pixbuf`.

### Installation

1. **Clone the repository**

    ```bash
    git clone <repository-url>
    cd inventory_control
    ```

2. **Set up the environment**

    Using **uv** (Recommended):

    ```bash
    uv sync
    ```

    Using **pip**:

    ```bash
    python -m venv .venv
    # linux/macOS
    source .venv/bin/activate
    # Windows
    .venv\Scripts\activate
    pip install -r pyproject.toml
    ```

3. **Configure Environment Variables**
    Create a `.env` file in the root directory.

    **Development (SQLite — no database setup needed):**

    ```ini
    DEBUG=True
    SECRET_KEY=your-secret-key-here
    ALLOWED_HOSTS=localhost,127.0.0.1
    ```

    **Production (PostgreSQL):**

    ```ini
    DEBUG=False
    SECRET_KEY=your-strong-secret-key-here
    ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

    # PostgreSQL — all four DB_* variables must be set to activate PostgreSQL.
    # If DB_NAME is absent or empty, Django falls back to SQLite automatically.
    DB_NAME=inventory_db
    DB_USER=inventory_user
    DB_PASSWORD=your-db-password
    DB_HOST=localhost
    DB_PORT=5432
    ```

    > **Note:** Media uploads (item images) are stored under `media/` in the project root.
    > Make sure this directory is writable and served by your web server in production.

4. **Run Migrations**

    ```bash
    uv run python manage.py migrate
    ```

5. **Create a Superuser**

    ```bash
    uv run python manage.py createsuperuser
    ```

6. **Run the Development Server**

    ```bash
    uv run python manage.py runserver
    ```

    Visit `http://127.0.0.1:8000` in your browser.

## 📁 Project Structure

* `core/`: Application entry point, settings, and global configurations.
* `inventory/`: Core engine managing items, warehouses, multi-step transactions, and auditing.
* `administration/`: Governance layer managing the University hierarchy (Faculties, Departments) and extended user profiles.
* `templates/`: UI layer with clean, modular HTML components.
* `static/`: Production-ready assets (CSS, JS, Images).
* `SQL/`: Database initialization and migration scripts.
* `documentation/`: Project diagrams (ERD) and technical notes.

## 🤝 Credits

Developed by **GSCC - Center for Software Development and Information Technology**, Benha University.
© 2025 All Rights Reserved.
