-- Supabase SQL Editor에서 실행하세요
-- https://supabase.com/dashboard/project/vkrbdqzwvflrmgwelmfo/sql/new

CREATE TABLE IF NOT EXISTS members (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  name        text NOT NULL,
  dept        text,
  year        text,
  job_type    text,
  current     text,
  is_current  boolean DEFAULT false,
  experiences jsonb DEFAULT '[]',
  education   jsonb DEFAULT '[]',
  awards      jsonb DEFAULT '[]',
  certs       jsonb DEFAULT '[]',
  etc         jsonb DEFAULT '[]',
  linkedin    text,
  activities  jsonb DEFAULT '[]',
  created_at  timestamptz DEFAULT now()
);

-- 누구나 조회 가능
ALTER TABLE members ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_all"   ON members FOR SELECT USING (true);
CREATE POLICY "insert_all" ON members FOR INSERT WITH CHECK (true);
CREATE POLICY "update_all" ON members FOR UPDATE USING (true);