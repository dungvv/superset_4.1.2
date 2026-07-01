INSERT INTO summarize_finance_deduct_temp (home_plmn_id,home_code,pay_group_id,group_code,group_name,plmn_id,group_order,type_sum,country,name,code,ty_gia,period,
tt_extax_sdr,tt_intax_sdr,tt_extax_usd,
                                          tt_intax_usd,tt_extax_vnd,tt_intax_vnd,ds_extax_sdr,ds_tax_sdr,ds_intax_sdr,ds_extax_usd,ds_intax_usd,ds_extax_vnd,
                                          ds_intax_vnd,
                                          gtt_extax_sdr,gtt_intax_sdr,gtt_extax_usd,gtt_intax_usd,gtt_extax_vnd,gtt_intax_vnd,status_ds,status_data,cross_date)
SELECT *
 FROM (
       SELECT  home_plmn_id,home_code,pay_group_id,group_code,group_name,plmn_id,group_order,'CPSP' type,country,name,code,
               f_exchange_rate(period,'O') as ty_gia,DATE_FORMAT(period, '%Y-%m-01') period,
               tt_extax_sdr,tt_intax_sdr,tt_extax_usd,tt_intax_usd,tt_extax_vnd,tt_intax_vnd,
               ds_extax_sdr,ds_tax_sdr,ds_intax_sdr,ds_extax_usd,ds_intax_usd,ds_extax_vnd,ds_intax_vnd,
               CASE WHEN status_ds = '1' THEN tt_extax_sdr ELSE 0 END gtt_extax_sdr,
               CASE WHEN status_ds = '1' THEN tt_intax_sdr ELSE 0 END gtt_intax_sdr,
               CASE WHEN status_ds = '1' THEN tt_extax_usd ELSE 0 END gtt_extax_usd,
               CASE WHEN status_ds = '1' THEN tt_intax_usd ELSE 0 END gtt_intax_usd,
               CASE WHEN status_ds = '1' THEN tt_extax_vnd ELSE 0 END gtt_extax_vnd,
               CASE WHEN status_ds = '1' THEN tt_intax_vnd ELSE 0 END gtt_intax_vnd,
               status_ds,0 status_data,STR_TO_DATE(p_thang_doi_soat, '%m/%Y') cross_date
       FROM
            (
--------------------------------------------------------------------------------
----1. Co ca so lieu tam tinh va so lieu doi soat trong ky:
--------------------------------------------------------------------------------
             SELECT b.home_plmn_id,b.home_code,b.payGroupId pay_group_id,b.groupCode group_code,b.groupName group_name,b.plmn_id,b.group_order,
                    a.country, a.name,a.code, a.period,
                    round(a.exvat_sdr,2) tt_extax_sdr,round(a.invat_sdr,2) tt_intax_sdr,
                    round(a.exvat, 2) tt_extax_usd,round(a.invat, 2) tt_intax_usd,
                    round(round(a.exvat, 2)* f_exchange_rate(period, 'O')) tt_extax_vnd,
                    round(round(a.invat, 2)* f_exchange_rate(period, 'O')) tt_intax_vnd,
                    b.country_name,b.network_name,b.network_code,b.bill_cycle,
                    round(b.doanhthu_sdr, 2) ds_extax_sdr,round(b.vat_sdr, 2) ds_tax_sdr,round(b.total_sdr , 2) ds_intax_sdr,
                    round(b.doanhthu_usd,2) ds_extax_usd,round(b.total_usd,2) ds_intax_usd,
                    b.doanhthu_vnd ds_extax_vnd,b.total_vnd ds_intax_vnd,
                    '1' status_ds  -- Da doi soat
             FROM SUMMARIZE_FINANCE_TEMP a
             JOIN (  SELECT 1 home_plmn_id, 'VNMVT' home_code,
                              IFNULL(pi.pay_group_id,0) as payGroupId,
                              IFNULL((select code from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 'MANG_DOI_SOAT_TRUC_TIEP' ELSE 'SYNIVERSE' END) AS groupCode,
                              IFNULL((select name from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 'MANG_DOI_SOAT_TRUC_TIEP' ELSE 'SYNIVERSE' END) AS groupName,
                              IFNULL((select code from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 1 ELSE 2 END) as group_order,
                              pi.country AS country_name, pi.plmn_id,pi.code AS network_code, pi.name AS network_name,
                              'I' direction,bill_cycle,cross_date, a.fileName AS fileName,
                              IFNULL(a.doanhthu_sdr, 0)as doanhthu_sdr,IFNULL(a.vat_sdr, 0) as vat_sdr,IFNULL(a.total_sdr, 0) as total_sdr,
                              round(IFNULL(a.doanhthu_sdr, 0), 2) as doanhthu_usd,round(IFNULL(a.vat_usd, 0), 2) as vat_usd,
                              round(IFNULL(a.total_sdr, 0)* f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 2) AS total_usd,
                              round(round(IFNULL(a.doanhthu_USD, 0), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle, rate_type), 0)AS doanhthu_VND,
                              round(round(IFNULL(a.vat_USD, 0), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle, rate_type), 0)AS vat_VND,
                              --round(round(IFNULL(a.doanhthu_USD,0),2)* f_get_exchange_rate('USD', 'VND',bill_cycle, rate_type),0) +
                              round(round(IFNULL(a.vat_USD,0),2)*f_get_exchange_rate('USD', 'VND',bill_cycle, rate_type),0) as total_VND,
                              round(round(IFNULL(a.total_SDR, 0)* f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle,
                              rate_type), 0) AS total_VND,
                              0 approval,NOW() sum_date
       FROM (   SELECT id.plmn_id,id.name AS fileName,id.cross_date,id.bill_cycle,
                        (CASE WHEN ((id.direction = 'I' AND id.crc_type IN ('M', 'D', 'S', 'C') AND id.home_plmn_id = 1)
                                        OR (id.direction = 'I' AND id.crc_type = 'M' AND id.home_plmn_id != 1)
                                        OR (id.direction = 'I' AND id.crc_type IN ('H', 'B'))
                                        OR (id.direction = 'O' AND id.crc_type = 'M' AND id.home_plmn_id != 1)) THEN 2
                            ELSE 1 END) rate_type,
                        CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.pre_tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) ) END END) , 5) END AS doanhthu_SDR,
                        CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN 0 ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN 0 ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) )*(CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END) END END), 5) END AS vat_SDR,
                        ROUND(SUM(IFNULL(id.total_crc_data, 0)), 5) AS total_sdr,
                        ROUND(CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.pre_tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) ) END END , 5) END * f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 5) AS doanhthu_USD,
                        ROUND(CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN 0 ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN 0 ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) )*(CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END) END END), 5) END * f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 5) AS vat_USD,
                        '' AS noteReport
                FROM dch_crc_data id
                WHERE  id.status <> 1 AND id.direction = 'I'   --- Tham so huong TAP file (= huong hoa don)
                    AND DATE_FORMAT(id.cross_date, '%Y-%m-01') = STR_TO_DATE(p_thang_doi_soat, '%m/%Y') -- Tham so Thang doi soat
                    AND id.crc_type IN ('D', 'M') AND id.home_plmn_id = 1
                GROUP BY id.plmn_id,cross_date,bill_cycle,direction, name,
                        (CASE WHEN ((id.direction = 'I' AND id.crc_type IN ('M', 'D', 'S', 'C') AND id.home_plmn_id = 1)
                                        OR (id.direction = 'I' AND id.crc_type = 'M' AND id.home_plmn_id != 1)
                                        OR (id.direction = 'I' AND id.crc_type IN ('H', 'B'))
                                        OR (id.direction = 'O' AND id.crc_type = 'M' AND id.home_plmn_id != 1)) THEN 2
                            ELSE 1 END)
            )a
            LEFT JOIN plmn_info pi ON a.plmn_id = pi.plmn_id
        WHERE a.doanhthu_SDR >= 0 AND pi.type <> 'H'
            AND (pi.pay_group_id IS NULL OR pi.pay_group_id NOT IN (SELECT pay_group_id FROM payment_group WHERE  TYPE = 1))
            AND (pi.pay_group_id IN (SELECT pay_group_id  FROM payment_group  WHERE TYPE <> 1) OR (pi.pay_group_id IS NULL AND pi.TYPE <> 'S'))
            AND a.plmn_id NOT IN ( SELECT plmn_id FROM plmn_info  WHERE pay_group_id = 125)  --Bo GLOBAL SIM - y/c k DONG BO BCCS
        ORDER BY pi.TYPE, pi.code) b
     ON a.period = b.bill_cycle AND a.code = b.network_code
     AND CASE WHEN a.direction = 'I' THEN 'I' WHEN a.direction = 'O' THEN 'I' ELSE 'O' END = b.direction
     AND bill_cycle = STR_TO_DATE(p_thang_doi_soat, '%m/%Y')
     AND a.direction = 'O'

UNION
--------------------------------------------------------------------------------
----2. Co so tam tinh trong ky va khong co so doi soat ---
--------------------------------------------------------------------------------
    SELECT 1 home_plmn_id,'VNMVT' home_code,IFNULL(pi.pay_group_id,0) as pay_group_id,
           IFNULL((select code from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 'MANG_DOI_SOAT_TRUC_TIEP' ELSE 'SYNIVERSE' END) AS group_code,
           IFNULL((select name from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 'MANG_DOI_SOAT_TRUC_TIEP' ELSE 'SYNIVERSE' END) AS group_name,
           pi.plmn_id,
           IFNULL((select code from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 1 ELSE 2 END) as group_order,
           a.country,a.name,a.code,a.period,
           round(a.exvat_sdr,2) tt_extax_sdr,round(a.invat_sdr,2) tt_intax_sdr,
           round(a.exvat, 2) tt_extax_usd,round(a.invat, 2) tt_intax_usd,
           round(round(a.exvat, 2)* f_exchange_rate(period, 'O')) tt_extax_vnd,
           round(round(a.invat, 2)* f_exchange_rate(period, 'O')) tt_intax_vnd,
           '' country_name,'' network_name,'' network_code,NULL bill_cycle,
           0 ds_extax_sdr,0 ds_tax_sdr,0 ds_intax_sdr,0 ds_extax_usd,0 ds_intax_usd,0 ds_extax_vnd,0 ds_intax_vnd,
           '0' status_ds --Chua doi soat
    FROM SUMMARIZE_FINANCE_TEMP a, plmn_info pi
    WHERE 1 = 1 and a.code = pi.code AND a.period = STR_TO_DATE(p_thang_doi_soat, '%m/%Y') AND direction = 'O'
      AND NOT EXISTS (SELECT * FROM
          (SELECT 1 home_plmn_id, 'VNMVT' home_code,  pi.country AS country_name,pi.plmn_id, pi.code AS network_code,pi.name AS network_name,
                  'I' direction,bill_cycle,cross_date,a.fileName AS fileName,
                  IFNULL(a.doanhthu_SDR, 0)AS doanhthu_SDR, IFNULL(a.vat_SDR, 0)AS vat_SDR,IFNULL(a.total_SDR, 0)AS total_SDR,
                  round(IFNULL(a.doanhthu_USD, 0), 2) AS doanhthu_USD,round(IFNULL(a.vat_USD, 0), 2) AS vat_USD,
                  round(IFNULL(a.total_SDR, 0)* f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 2) AS total_USD,
                  round(round(IFNULL(a.doanhthu_USD, 0), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle, rate_type), 0)AS doanhthu_VND,
                  round(round(IFNULL(a.vat_USD, 0), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle, rate_type), 0)AS vat_VND,
                  --round(round(IFNULL(a.doanhthu_USD,0),2)* f_get_exchange_rate('USD', 'VND',bill_cycle, rate_type),0) +
                  round(round(IFNULL(a.vat_USD,0),2)*f_get_exchange_rate('USD', 'VND',bill_cycle, rate_type),0) as total_VND,
                  round(round(IFNULL(a.total_SDR, 0)* f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle,
                  rate_type), 0) AS total_VND,
                  0 approval,NOW() sum_date
           FROM (SELECT id.plmn_id,id.name AS fileName,id.cross_date,id.bill_cycle,
                         (CASE WHEN ((id.direction = 'I' AND id.crc_type IN ('M', 'D', 'S', 'C') AND id.home_plmn_id = 1)
                                         OR (id.direction = 'I' AND id.crc_type = 'M' AND id.home_plmn_id != 1)
                                         OR (id.direction = 'I' AND id.crc_type IN ('H', 'B'))
                                         OR (id.direction = 'O' AND id.crc_type = 'M' AND id.home_plmn_id != 1)) THEN 2
                             ELSE 1 END) rate_type,
                         CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.pre_tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) ) END END , 5) END AS doanhthu_SDR,
                         CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN 0 ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN 0 ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) )*(CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END) END END), 5) END AS vat_SDR,
                         ROUND(SUM(IFNULL(id.total_crc_data, 0)), 5) AS total_sdr,
                         ROUND(CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.pre_tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) ) END END , 5) END * f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 5) AS doanhthu_USD,
                         ROUND(CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN 0 ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN 0 ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) )*(CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END) END END), 5) END * f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 5) AS vat_USD,
                         '' AS noteReport
                 FROM dch_crc_data id
                 WHERE id.status <> 1 AND id.direction = 'I' AND id.crc_type IN ('D', 'M') AND id.home_plmn_id = 1
                     AND DATE_FORMAT(id.cross_date, '%Y-%m-01') = STR_TO_DATE(p_thang_doi_soat, '%m/%Y')
                 --and plmn_id =15
                 GROUP BY id.plmn_id,cross_date, bill_cycle,direction, name,
                         (CASE WHEN ((id.direction = 'I' AND id.crc_type IN ('M', 'D', 'S', 'C') AND id.home_plmn_id = 1)
                                         OR (id.direction = 'I' AND id.crc_type = 'M' AND id.home_plmn_id != 1)
                                         OR (id.direction = 'I' AND id.crc_type IN ('H', 'B'))
                                         OR (id.direction = 'O' AND id.crc_type = 'M' AND id.home_plmn_id != 1)) THEN 2
                             ELSE 1 END)
             )a
             LEFT JOIN plmn_info pi ON a.plmn_id = pi.plmn_id
         WHERE a.doanhthu_SDR >= 0 AND pi.type <> 'H'-- khac VNMVT
             AND (pi.pay_group_id IS NULL OR pi.pay_group_id NOT IN (SELECT pay_group_id FROM payment_group WHERE TYPE = 1))
             AND (pi.pay_group_id IN (SELECT pay_group_id FROM payment_group WHERE TYPE <> 1) OR (pi.pay_group_id IS NULL AND pi.TYPE <> 'S')) -- code
             -- khong phai thi truong khong thuoc partner group
             AND a.plmn_id NOT IN ( SELECT plmn_id  FROM plmn_info  WHERE pay_group_id = 125) --Bo GLOBAL SIM - y/c k DONG BO BCCS
             --- => bo qua nhom global sim va khac sub va khac vnmvt -> model type hub?
         ORDER BY pi.TYPE,pi.code ) b
     WHERE 1 = 1 AND a.period = b.bill_cycle AND b.bill_cycle = b.cross_date AND b.network_code = a.code
     AND CASE WHEN a.direction = 'I' THEN 'O' WHEN a.direction = 'O' THEN 'I' ELSE '1' END = b.direction )

UNION
--------------------------------------------------------------------------------
----3. Co so lieu doi soat cua ky cu truoc do ----> Lay ca so tam tinh va so doi soat cua ky cu len
--------------------------------------------------------------------------------
    SELECT b.home_plmn_id,b.home_code,b.payGroupId pay_group_id,b.groupCode group_code,b.groupName group_name,b.plmn_id,b.group_order,
           a.country,a.name,a.code,a.period,
           round(a.exvat_sdr,2) tt_extax_sdr,round(a.invat_sdr,2) tt_intax_sdr,
           round(a.exvat, 2) tt_extax_usd,round(a.invat, 2) tt_intax_usd,
           round(round(a.exvat, 2)* f_exchange_rate(period, 'O')) tt_extax_vnd,
           round(round(a.invat, 2)* f_exchange_rate(period, 'O')) tt_intax_vnd,
           b.country_name,b.network_name,b.network_code,b.bill_cycle,
           round(b.doanhthu_sdr, 2) ds_extax_sdr,round(b.vat_sdr, 2) ds_tax_sdr,round(b.total_sdr, 2) ds_intax_sdr,
           round(b.doanhthu_usd, 2) ds_extax_usd,round(b.total_usd, 2) ds_intax_usd,
           doanhthu_vnd ds_extax_vnd,total_vnd ds_intax_vnd,
           '1' status_ds -- Da doi soat
     FROM SUMMARIZE_FINANCE_TEMP a
     JOIN (SELECT  1 home_plmn_id,'VNMVT' home_code,
                   IFNULL(pi.pay_group_id,0) as payGroupId,
                   IFNULL((select code from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 'MANG_DOI_SOAT_TRUC_TIEP' ELSE 'SYNIVERSE' END) AS groupCode,
                   IFNULL((select name from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 'MANG_DOI_SOAT_TRUC_TIEP' ELSE 'SYNIVERSE' END) AS groupName,
                   IFNULL((select code from payment_group where pay_group_id = pi.pay_group_id), CASE WHEN pi.direct = 1 THEN 1 ELSE 2 END) as group_order,
                   pi.country AS country_name,pi.plmn_id,
                   pi.code AS network_code, pi.name AS network_name,'I' direction, bill_cycle, cross_date,a.fileName AS fileName,
                   IFNULL(a.doanhthu_SDR, 0)AS doanhthu_SDR,IFNULL(a.vat_SDR, 0)AS vat_SDR,IFNULL(a.total_SDR, 0)AS total_SDR,
                   round(IFNULL(a.doanhthu_USD, 0), 2) AS doanhthu_USD,round(IFNULL(a.vat_USD, 0), 2) AS vat_USD,
                   round(IFNULL(a.total_SDR, 0)* f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 2) AS total_USD,
                   round(round(IFNULL(a.doanhthu_USD, 0), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle, rate_type), 0)AS doanhthu_VND,
                   round(round(IFNULL(a.vat_USD, 0), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle, rate_type), 0)AS vat_VND,
                   --round(round(IFNULL(a.doanhthu_USD,0),2)* f_get_exchange_rate('USD', 'VND',bill_cycle, rate_type),0) +
                   round(round(IFNULL(a.vat_USD,0),2)*f_get_exchange_rate('USD', 'VND',bill_cycle, rate_type),0) as total_VND,
                   round(round(IFNULL(a.total_SDR, 0)* f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 2)* f_get_exchange_rate('USD', 'VND', bill_cycle,
                   rate_type), 0) AS total_VND,
                   0 approval,NOW() sum_date
            FROM (SELECT id.plmn_id,id.name AS fileName,id.cross_date,id.bill_cycle,
                         (CASE WHEN ((id.direction = 'I' AND id.crc_type IN ('M', 'D', 'S', 'C') AND id.home_plmn_id = 1)
                                         OR (id.direction = 'I' AND id.crc_type = 'M' AND id.home_plmn_id != 1)
                                         OR (id.direction = 'I' AND id.crc_type IN ('H', 'B'))
                                         OR (id.direction = 'O' AND id.crc_type = 'M' AND id.home_plmn_id != 1)) THEN 2
                             ELSE 1 END) rate_type,
                         CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.pre_tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) ) END END , 5) END AS doanhthu_SDR,
                         CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN 0 ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN 0 ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) )*(CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END) END END), 5) END AS vat_SDR,
                         ROUND(SUM(IFNULL(id.total_crc_data, 0)), 5) AS total_sdr,
                         ROUND(CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.pre_tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN SUM(ROUND(IFNULL(id.total_crc_data, 0), 5)) ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) ) END END , 5) END * f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 5) AS doanhthu_USD,
                         ROUND(CASE WHEN SUM(id.total_crc_data) = SUM(id.total_home_data) THEN ROUND(SUM(IFNULL(id.tax_home_data, 0)), 5) ELSE ROUND( (CASE WHEN SUM(IFNULL(id.tax_home_data, 0)) <= 0 THEN 0 ELSE CASE WHEN SUM(IFNULL(id.pre_tax_home_data, 0)) <= 0 THEN 0 ELSE SUM(ROUND(IFNULL(id.total_crc_data, 0), 5))/(1 + (CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END)) )*(CASE WHEN SUM(tax_home_data) IS NULL THEN 0 WHEN SUM(tax_home_data) = 0 THEN 0 ELSE IFNULL(SUM(id.tax_home_data), 0)/ SUM(id.pre_tax_home_data) END) END END), 5) END * f_get_exchange_rate('SDR', 'USD', bill_cycle, 1), 5) AS vat_USD,
                          '' AS noteReport
                    FROM dch_crc_data id
                    WHERE id.status <> 1 AND id.direction = 'I'
                        AND DATE_FORMAT(id.cross_date, '%Y-%m-01') = STR_TO_DATE(p_thang_doi_soat, '%m/%Y')
                        AND id.crc_type IN ('D', 'M') AND id.home_plmn_id = 1
                        --and plmn_id =15
                    GROUP BY id.plmn_id, cross_date,bill_cycle,direction,name,
                            (CASE WHEN ((id.direction = 'I' AND id.crc_type IN ('M', 'D', 'S', 'C') AND id.home_plmn_id = 1)
                                            OR (id.direction = 'I' AND id.crc_type = 'M'AND id.home_plmn_id != 1)
                                            OR (id.direction = 'I' AND id.crc_type IN ('H', 'B'))
                                            OR (id.direction = 'O' AND id.crc_type = 'M' AND id.home_plmn_id != 1)) THEN 2
                                ELSE 1 END)
                )a
                LEFT JOIN plmn_info pi ON a.plmn_id = pi.plmn_id
            WHERE a.doanhthu_SDR >= 0 AND pi.type <> 'H'
                AND (pi.pay_group_id IS NULL OR pi.pay_group_id NOT IN (SELECT pay_group_id FROM payment_group WHERE  TYPE = 1))
                AND (pi.pay_group_id IN (SELECT pay_group_id FROM payment_group  WHERE TYPE <> 1) OR (pi.pay_group_id IS NULL AND pi.TYPE <> 'S'))
                AND a.plmn_id NOT IN (SELECT plmn_id FROM plmn_info  WHERE pay_group_id = 125) --Bo GLOBAL SIM - y/c k DONG BO BCCS
            ORDER BY pi.TYPE, pi.code ) b
     ON a.period != b.cross_date AND a.period = b.bill_cycle AND a.code = b.network_code
     AND CASE WHEN a.direction = 'I' THEN 'O' WHEN a.direction = 'O' THEN 'I' ELSE '1' END = b.direction
         AND b.cross_date = STR_TO_DATE(p_thang_doi_soat, '%m/%Y')  -- Tham so thang doi soat
         AND a.direction = 'O' -- Huong Roaming
     )a )
WHERE round(gtt_extax_usd,2) > 0
ORDER BY pay_group_id,group_code,code;
