-- Create a function to fix duplicates for from_sub_warehouse
CREATE OR REPLACE FUNCTION fix_duplicate_doc_numbers_from()
RETURNS VOID AS $$
DECLARE
    dup_record RECORD;
    trans_record RECORD;
    counter INTEGER;
    new_doc_number VARCHAR(50);
BEGIN
    -- Loop through all duplicate combinations
    FOR dup_record IN 
        SELECT transaction_type, from_sub_warehouse_id, document_number
        FROM inventory_itemtransactions
        WHERE transaction_type IN ('D', 'T')
            AND document_number IS NOT NULL
            AND document_number != ''
        GROUP BY transaction_type, from_sub_warehouse_id, document_number
        HAVING COUNT(*) > 1
    LOOP
        counter := 1;
        -- Update all but the first occurrence
        FOR trans_record IN 
            SELECT id
            FROM inventory_itemtransactions
            WHERE transaction_type = dup_record.transaction_type
                AND from_sub_warehouse_id IS NOT DISTINCT FROM dup_record.from_sub_warehouse_id
                AND document_number = dup_record.document_number
            ORDER BY created_at
            OFFSET 1  -- Skip the first one
        LOOP
            new_doc_number := dup_record.document_number || '-DUP-' || counter;
            UPDATE inventory_itemtransactions
            SET document_number = new_doc_number
            WHERE id = trans_record.id;
            counter := counter + 1;
            RAISE NOTICE 'Updated transaction %: % -> %', trans_record.id, dup_record.document_number, new_doc_number;
        END LOOP;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Create a function to fix duplicates for to_sub_warehouse
CREATE OR REPLACE FUNCTION fix_duplicate_doc_numbers_to()
RETURNS VOID AS $$
DECLARE
    dup_record RECORD;
    trans_record RECORD;
    counter INTEGER;
    new_doc_number VARCHAR(50);
BEGIN
    -- Loop through all duplicate combinations
    FOR dup_record IN 
        SELECT transaction_type, to_sub_warehouse_id, document_number
        FROM inventory_itemtransactions
        WHERE transaction_type IN ('A', 'R')
            AND document_number IS NOT NULL
            AND document_number != ''
        GROUP BY transaction_type, to_sub_warehouse_id, document_number
        HAVING COUNT(*) > 1
    LOOP
        counter := 1;
        -- Update all but the first occurrence
        FOR trans_record IN 
            SELECT id
            FROM inventory_itemtransactions
            WHERE transaction_type = dup_record.transaction_type
                AND to_sub_warehouse_id IS NOT DISTINCT FROM dup_record.to_sub_warehouse_id
                AND document_number = dup_record.document_number
            ORDER BY created_at
            OFFSET 1  -- Skip the first one
        LOOP
            new_doc_number := dup_record.document_number || '-DUP-' || counter;
            UPDATE inventory_itemtransactions
            SET document_number = new_doc_number
            WHERE id = trans_record.id;
            counter := counter + 1;
            RAISE NOTICE 'Updated transaction %: % -> %', trans_record.id, dup_record.document_number, new_doc_number;
        END LOOP;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Execute the functions
SELECT fix_duplicate_doc_numbers_from();
SELECT fix_duplicate_doc_numbers_to();

-- Clean up functions
DROP FUNCTION IF EXISTS fix_duplicate_doc_numbers_from();
DROP FUNCTION IF EXISTS fix_duplicate_doc_numbers_to();