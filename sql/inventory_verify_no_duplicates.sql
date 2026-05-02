-- Verify no more duplicates for from_sub_warehouse
SELECT 
    transaction_type,
    from_sub_warehouse_id,
    document_number,
    COUNT(*) as count
FROM inventory_itemtransactions
WHERE transaction_type IN ('D', 'T')
    AND document_number IS NOT NULL
    AND document_number != ''
GROUP BY transaction_type, from_sub_warehouse_id, document_number
HAVING COUNT(*) > 1;

-- Verify no more duplicates for to_sub_warehouse
SELECT 
    transaction_type,
    to_sub_warehouse_id,
    document_number,
    COUNT(*) as count
FROM inventory_itemtransactions
WHERE transaction_type IN ('A', 'R')
    AND document_number IS NOT NULL
    AND document_number != ''
GROUP BY transaction_type, to_sub_warehouse_id, document_number
HAVING COUNT(*) > 1;

-- Both queries should return 0 rows