-- Should return 0 if all FacultyItemStock records now match transaction history
SELECT count(*)
FROM inventory_facultyitemstock fis
LEFT JOIN inventory_item i ON fis.item_id = i.id
LEFT JOIN inventory_itemcategory ic ON i.category_id = ic.id
WHERE ic.sub_warehouse_id != fis.sub_warehouse_id;