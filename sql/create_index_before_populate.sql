CREATE INDEX idx_it_details_txn ON inventory_itemtransactiondetails(transaction_id);
CREATE INDEX idx_it_txns_status ON inventory_itemtransactions(approval_status, deleted, is_reversed);