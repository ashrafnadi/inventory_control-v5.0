# inventory/signals.py
import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from administration.models import Faculty
from inventory.models import FacultyItemStock, Item

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Item)
def create_faculty_item_stock(sender, instance, created, **kwargs):
    """
    Automatically create FacultyItemStock records for ALL faculties
    when a new Item is created.
    """
    if not created:
        return

    logger.info(f"Creating FacultyItemStock for new item: {instance.name}")

    target_sub_warehouse = None
    if instance.category and hasattr(instance.category, "sub_warehouse"):
        target_sub_warehouse = instance.category.sub_warehouse

    if not target_sub_warehouse:
        logger.warning(
            f"Cannot create FacultyItemStock for item '{instance.name}': "
            f"category has no sub_warehouse"
        )
        return

    faculties = Faculty.objects.all()
    created_count = 0

    for faculty in faculties:
        stock, created = FacultyItemStock.objects.get_or_create(
            faculty=faculty,
            item=instance,
            sub_warehouse=target_sub_warehouse,
            defaults={
                "cached_quantity": 0,
                "limit_quantity": instance.limit_quantity,
            },
        )
        if created:
            created_count += 1

    logger.info(
        f"Created {created_count} FacultyItemStock records "
        f"for item '{instance.name}' across {faculties.count()} faculties"
    )


@receiver(pre_save, sender=Item)
def cache_old_category(sender, instance, **kwargs):
    """
    Cache the old category ID before save so we can compare in post_save.
    Only runs if the item already exists (not on creation).
    """
    if instance.pk:
        try:
            old_instance = Item.objects.get(pk=instance.pk)
            # Store old category ID on the instance for later comparison
            instance._old_category_id = old_instance.category_id
        except Item.DoesNotExist:
            pass


@receiver(post_save, sender=Item)
def sync_faculty_stock_on_category_change(sender, instance, created, **kwargs):
    """
    Update FacultyItemStock.sub_warehouse ONLY when Item.category changes.
    Ignores all other field edits (limit_quantity, name, etc.).
    """
    # Skip on creation - handled by separate signal if needed
    if created:
        return

    # Check if category actually changed
    old_category_id = getattr(instance, "_old_category_id", None)
    new_category_id = instance.category_id

    # If category didn't change, exit early (do nothing)
    if old_category_id == new_category_id:
        return

    logger.info(
        f"Category changed for item '{instance.name}': "
        f"{old_category_id} → {new_category_id}. Updating FacultyItemStock..."
    )

    # Get the NEW sub_warehouse from the new category
    new_sub_warehouse = None
    if instance.category and hasattr(instance.category, "sub_warehouse"):
        new_sub_warehouse = instance.category.sub_warehouse

    if not new_sub_warehouse:
        logger.warning(
            f"Cannot update FacultyItemStock for item '{instance.name}': "
            f"new category has no sub_warehouse"
        )
        return

    # UPDATE EXISTING FacultyItemStock records to new sub_warehouse
    with transaction.atomic():
        # Find all FacultyItemStock records for this item
        stocks = FacultyItemStock.objects.filter(item=instance).select_for_update()

        updated_count = 0
        for stock in stocks:
            # Skip if already pointing to the correct sub_warehouse
            if stock.sub_warehouse_id == new_sub_warehouse.id:
                continue

            # Check if a record already exists for this faculty/item/new_sub_warehouse combo
            existing, _ = FacultyItemStock.objects.get_or_create(
                faculty=stock.faculty,
                item=instance,
                sub_warehouse=new_sub_warehouse,
                defaults={
                    "cached_quantity": stock.cached_quantity,
                    "limit_quantity": stock.limit_quantity,
                },
            )

            # If we created a new record or it's different, merge and delete old
            if existing.id != stock.id:
                # Merge quantities (optional: adjust logic based on business rules)
                existing.cached_quantity += stock.cached_quantity
                existing.save(update_fields=["cached_quantity"])
                # Delete the old record
                stock.delete()
            else:
                # Just update the sub_warehouse on the existing record
                stock.sub_warehouse = new_sub_warehouse
                stock.save(update_fields=["sub_warehouse"])

            updated_count += 1

    logger.info(
        f"Updated {updated_count} FacultyItemStock records "
        f"for item '{instance.name}' to new sub_warehouse '{new_sub_warehouse.name}'"
    )
