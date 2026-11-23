import copy
import unittest
from unittest.mock import patch
import stometric.web  # required: web defines dependencies before importing routers
from stometric.warehouse import plan, identity
from stometric.api_warehouse import access, snapshot
from fastapi import HTTPException

class WarehouseTests(unittest.TestCase):
 def setUp(self):
  self.source={'products':[{'id':1,'sku':'A','title':'Иглы'}], 'balances':[{'product_id':1,'location':'own','quantity':50}], 'shipments':[{'product_id':1,'quantity':200}], 'transfers':[{'product_id':1,'shop_id':1,'model':'FBO','quantity':10,'status':'packing'}], 'aliases':[{'shop_id':1,'sku':'A1','product_id':1},{'shop_id':2,'sku':'A2','product_id':1}]}
  self.reports={1:{'title':'Shop 1','rows':[{'sku':'A1','daily':10,'stock':0}]},2:{'title':'Shop 2','rows':[{'sku':'A2','daily':5,'stock':10}]}}
 def test_shared_pool_and_reservation_not_subtracted_twice(self):
  p=plan(self.source,{1:11,2:22},self.reports,7,0)['products'][0]
  self.assertEqual(p['own'],50);self.assertEqual(p['incoming'],200)
  self.assertEqual(p['to_ship'],50);self.assertEqual(p['channels'][0]['need'],60)
  self.assertEqual(p['channels'][0]['allocated'],50);self.assertEqual(p['channels'][1]['allocated'],0)
 def test_delivery_time_and_transit_reduce_need(self):
  p=plan(self.source,{1:11,2:22},self.reports,7,2)['products'][0]
  self.assertEqual(p['channels'][0]['need'],80)
 def test_missing_data_not_zero(self):
  self.reports[1]['rows'][0]['stock']=None
  ch=plan(self.source,{1:11,2:22},self.reports)['products'][0]['channels'][0]
  self.assertIsNone(ch['need']);self.assertIsNone(ch['days_left']);self.assertEqual(ch['allocated'],0)
 def test_stale_report_has_no_allocation(self):
  self.reports[1]['stale']=True
  p=plan(self.source,{1:11,2:22},self.reports)['products'][0]
  self.assertEqual(p['channels'][0]['allocated'],0);self.assertLessEqual(p['to_ship'],50)
 def test_ambiguous_alias_is_rejected(self):
  self.source['aliases'].append({'shop_id':1,'sku':'A1','product_id':2})
  r=plan(self.source,{1:11,2:22},self.reports)
  self.assertEqual(len(r['unmatched']),1)
 def test_does_not_fuzzy_match(self):
  self.reports[1]['rows'][0]['sku']='a1'
  self.assertEqual(len(plan(self.source,{1:11,2:22},self.reports)['unmatched']),1)
 def test_snapshot_unchanged(self):
  before=copy.deepcopy(self.source);plan(self.source,{1:11,2:22},self.reports)
  self.assertEqual(before,self.source)
 def test_identity_stable_no_key_exposure(self):
  self.assertEqual(identity('ozon','123'),identity('ozon','123'))
  self.assertNotEqual(identity('wb','123'),identity('ozon','123'))
 def test_no_support_bypass(self):
  with patch('stometric.api_warehouse.config.env', return_value={'FIRST_ADMIN_EMAIL':'owner@example.com'}):
   for user in ({'email':'other@example.com','is_superadmin':True},{'email':'owner@example.com','_mcp':{'shops':[1]}}):
    with self.assertRaises(HTTPException) as ctx:access(None,user)
    self.assertEqual(ctx.exception.status_code,403)
 def test_unrestricted_owner_membership_required(self):
  class C:
   def execute(self,*args):return self
   def fetchall(self):return []
  with patch('stometric.api_warehouse.config.env', return_value={'FIRST_ADMIN_EMAIL':'owner@example.com'}):
   with self.assertRaises(HTTPException):access(C(),{'id':1,'email':'owner@example.com'})
 def test_source_unconfigured_fails_closed(self):
  with patch('stometric.api_warehouse.config.env',return_value={}),patch('stometric.api_warehouse._snapshot',None):
   with self.assertRaises(HTTPException) as e:snapshot()
   self.assertEqual(e.exception.status_code,503)

if __name__=='__main__':unittest.main()
