# inventory/signals.py
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from administration.models import Faculty
from inventory.models import FacultyItemStock, Item

logger = logging.getLogger(__name__)


# inventory/signals.py
@receiver(post_save, sender=Item)
def create_faculty_item_stock(sender, instance, created, **kwargs):
    """
    Automatically create FacultyItemStock records for ALL faculties
    when a new Item is created.
    """
    if not created:
        return  # Only run on creation

    logger.info(f"Creating FacultyItemStock for new item: {instance.name}")

    # Get sub_warehouse from category (with safety check)
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
