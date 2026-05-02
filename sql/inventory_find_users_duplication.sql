SELECT 
    u.first_name, 
    STRING_AGG(u.id::text, ', ') as user_ids,
    STRING_AGG(d.id::text, ', ') as department_ids, 
    COUNT(*) as duplicate_count
FROM auth_user u,administration_department d,administration_userprofile p
WHERE u.id = p.user_id
AND p.department_id = d.id
GROUP BY u.first_name
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC;