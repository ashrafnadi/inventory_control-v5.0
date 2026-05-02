WITH CategorySWStats AS (
    SELECT 
        i.category_id,
        ic.sub_warehouse_id AS current_sw,
        sw_id,
        COUNT(*) AS frequency
    FROM inventory_itemtransactiondetails itd
    JOIN inventory_itemtransactions it ON itd.transaction_id = it.id
    JOIN inventory_item i ON itd.item_id = i.id
    JOIN inventory_itemcategory ic ON i.category_id = ic.id
    CROSS JOIN LATERAL (VALUES (it.from_sub_warehouse_id), (it.to_sub_warehouse_id)) AS v(sw_id)
    WHERE 
        it.approval_status = 'A' 
        AND it.deleted = FALSE 
        AND it.is_reversed = FALSE 
        AND sw_id IS NOT NULL
    GROUP BY i.category_id, ic.sub_warehouse_id, sw_id
),
MostFrequent AS (
    SELECT 
        category_id,
        current_sw,
        sw_id AS correct_sw,
        ROW_NUMBER() OVER (PARTITION BY category_id ORDER BY frequency DESC, current_sw = sw_id DESC) as rn
    FROM CategorySWStats
)
SELECT 
    ic.id AS cat_id,
    ic.name AS cat_name,
    mf.current_sw AS old_sw,
    mf.correct_sw AS new_sw
FROM MostFrequent mf
JOIN inventory_itemcategory ic ON mf.category_id = ic.id
WHERE mf.rn = 1 AND ic.sub_warehouse_id != mf.correct_sw
ORDER BY ic.id;