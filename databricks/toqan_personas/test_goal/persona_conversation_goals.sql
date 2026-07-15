-- Top 10 full conversations from a persona cluster (for LLM goal derivation).
--
-- Persona: persona_id = 3 (Relentless Troubleshooter)
-- Source: outputs_thesis/personas_databricks_data/personas.json
--
-- One row per turn. Includes origin_title + full user_message + assistant_reply
-- for the entire conversation (not session-windowed).
--
-- Export CSV → group by conversation_id → derive goal with your LLM.
--
-- Regenerate pool VALUES:
--   python databricks/toqan_personas/test_goal/generate_session_values.py --persona-id 3 --pool-size 60

WITH excluded_conversations AS (
  SELECT conversation_id FROM (
    VALUES
      ('465014e8-26c6-4950-b3a3-f1f6e07a4014'),
      ('fa519f19-7512-41ea-a703-ec90bfca3200'),
      ('4cfdaee6-331f-4b26-bb02-65a1f98dcea4'),
      ('3181b11f-e827-4044-b807-98c3f70a5534'),
      ('3aa84695-b0c4-4aeb-969f-7f1352f18b53')
  ) AS t(conversation_id)
),
pool AS (
  SELECT session_key FROM (
    VALUES
      ('ee1c75f1-2ad6-4de0-b352-32d0253e1fdc:019e8331-20cd-7a30-a51c-594840630b1d'),
      ('530f98f6-253d-4147-a40b-ec2f7d15be7e:019eca1a-2caa-7e5f-b804-e1275242eb49'),
      ('e62fd6bd-459a-456f-9cbb-fecf21114b5b:019e6ea8-68e2-7bf7-be4d-daffecbe846f'),
      ('efd20722-5eb2-4303-b824-aa6297ad851c:019eabff-5e32-736a-a640-84736fea7c36'),
      ('e86730e2-4318-4c76-ac15-bd4f9e5291bd:019e6405-18cd-7cda-a7e8-0375d87f7236'),
      ('9ae442a2-259c-4a18-bbbf-698be4774ddb:019e6995-7488-7937-90f4-db98c9b04c81'),
      ('7fce1470-d6dc-47f7-8e68-257ab57ec19b:019e3aa9-bf69-7ebe-b911-26c31c39f868'),
      ('17f013df-c2f0-4e9d-9d36-5ba04623bee5:019e681b-2351-76e8-bcca-b051be3bc906'),
      ('d60f3d97-039c-4868-9391-2d351c127c0b:019ecb74-826b-7a6e-8e65-87f6acdd81b5'),
      ('5b67f4d5-1fc6-4c2c-983e-dc20c1c28b64:019e6355-f2a1-7d99-9adf-167c0d79ba1e'),
      ('da6b7fd2-5877-49d1-bdaf-da6972985a59:019e6826-e660-72ce-9001-cbdee794c210'),
      ('b7653e0e-f3ba-4917-be0f-00003947c64c:019e6405-18cd-7cda-a7e8-0375d87f7236'),
      ('fd604cc2-dff6-4a71-afde-65032f0b7b76:019e8305-f289-7953-a148-6cfb740d7eaf'),
      ('3008b724-fabe-43f6-b2d3-e105485db8d7:019e888f-182d-7319-9b66-c0de19736802'),
      ('6820b990-2b51-4d94-be03-3caa2a1869e8:019e915e-d9ba-76ee-ae9e-7bcbcc8dedea'),
      ('ab23f4ae-ff7b-4438-857f-0043027d9b08:019e3af6-cf12-7817-a44a-a5830d4a2192'),
      ('76170bcc-4007-4c30-9e55-240941323414:019e4479-a0be-78e0-8b66-69073eb42553'),
      ('71fa0e4e-d259-4b41-aa95-1439350eaa0e:019e40be-a0ec-7a9e-a15d-3e4c3540e436'),
      ('75957179-0076-47cf-a6ca-0753986b02c5:019e3a48-63cb-7458-b08f-526ba9e4948a'),
      ('367e7661-3ac0-4412-8e73-6c6c16d0e6cb:019e3af6-cf12-7817-a44a-a5830d4a2192'),
      ('63e8d866-ff42-4c1f-8b99-46b5cbcfaa10:019e6405-18cd-7cda-a7e8-0375d87f7236'),
      ('25896351-b038-4c51-8d64-3cea4251b964:019eb644-6509-7d3e-9ed8-92d396ad5646'),
      ('a01dbafd-b5fc-457e-bee8-132b2bb1918c:019ecba2-9d13-727a-9748-f19ce879dca5'),
      ('bddd3d3b-49de-46ad-b2da-7c7cdf2a8ee2:019e72ee-4462-7c5b-a0bf-1a6f5655ca52'),
      ('7cbafa0c-437d-499f-8879-a7473a103a12:019e4adb-16d5-73f3-91a9-15fcfc4e28db'),
      ('773f7bb0-8ed3-4e2f-bfaa-4ed8d789805d:019eb5c8-ebe3-79c0-afda-fd283cf745c2'),
      ('afa3c8b9-5200-4f0e-b2a8-e9348469994c:019e69e7-6032-7009-be05-a577fe95499b'),
      ('d4971d61-2a7a-4663-9ddc-97002d8079c1:019e9819-9945-75b0-842f-142944117738'),
      ('b74ab26f-7fd8-4f9d-ba74-f5092b73fbd0:019e3af6-cf12-7817-a44a-a5830d4a2192'),
      ('c2245992-3025-45b8-a912-0c0cfd7805f9:019e92d9-6f59-7875-ada5-531ea385a4d3'),
      ('02131f09-18b7-4897-a965-d4fc19e1d612:019e97d4-f951-7cc6-93ed-8faa0cbbd891'),
      ('9352d474-ac18-4447-be64-91295436e9fb:019ed163-2785-7fd3-95e9-0b7977ed7be6'),
      ('11d0f5e1-10cb-4fda-9974-77f5e83e31d8:019e97d4-f951-7cc6-93ed-8faa0cbbd891'),
      ('9a8b8c61-6d30-4cf2-975e-336a125e456e:019e8266-7327-7aa9-9d6c-825ad32e8737'),
      ('d05b076d-9fe6-4b84-9cbc-b285fdb68e5d:019e40be-a0ec-7a9e-a15d-3e4c3540e436'),
      ('692da99c-6273-471d-ae54-649199a6db31:019eb7c1-3508-7586-8ae7-3e79cd732d26'),
      ('5a6de065-20a1-474c-a99a-f0bf86493ad3:019eb046-a01b-7537-ba76-724633dafced'),
      ('936bf067-9230-4dad-9191-56452a873465:019e45ce-e00d-7ac3-81b9-f76a6cd8a6d9'),
      ('20fa5206-f0f8-4108-9f3b-9dd19ced29bd:019e6355-f2a1-7d99-9adf-167c0d79ba1e'),
      ('0bd38981-1db5-4a18-a0d8-66f7927399c5:019e7451-5299-77c1-bd13-bf5ebdfbc5ed'),
      ('3ad647df-b679-421b-b89e-2a4bac648689:019e645f-b84c-7f0a-9076-c6059ac15a2e'),
      ('853dd4ec-8104-4198-bfd9-e31d8356801d:019e6355-f2a1-7d99-9adf-167c0d79ba1e'),
      ('c8862aaa-e0cc-4d09-adae-0c26ac27c519:019eb1aa-6882-7ac4-82df-c04876e981cb'),
      ('fc06a3a0-cd86-401a-9a58-91fdd49c073b:019e97d4-f951-7cc6-93ed-8faa0cbbd891'),
      ('7f2e4a3d-ed08-42a6-a38f-e267be8a8708:019e6405-18cd-7cda-a7e8-0375d87f7236'),
      ('9200c5ab-7b5c-4cf9-865c-1ddb5863cf30:019eb69a-ccc4-7136-979e-fd740273e31f'),
      ('ed025886-84f2-4334-b643-4223610e7627:019e6405-18cd-7cda-a7e8-0375d87f7236'),
      ('27cccaee-2088-46b5-946b-0e86f25928b5:019e3a82-f276-7ab2-ada4-8aabe6e06f38'),
      ('e7294d09-4da7-4817-8398-9c7e25f7703b:019ed0b4-4e4c-73f1-9e91-5eeed5a9e5fb'),
      ('61bad807-8fb4-4386-b240-cf74c9833b59:019e8c75-a07f-7ff4-bf23-593cee25a850'),
      ('10cc6cae-483e-4026-9824-bb61658da148:019e97d4-f951-7cc6-93ed-8faa0cbbd891'),
      ('c08bad1a-a84c-43cd-9680-5c98700ee8f8:019e9743-49fb-7862-9a76-fd2cfeb727a1'),
      ('bcf21561-a06c-4be0-baf4-102dc7f0ce41:019e91d5-b4e8-75e2-9c77-1b0e2ac3f48c'),
      ('7cbafa0c-437d-499f-8879-a7473a103a12:019e8305-f289-7953-a148-6cfb740d7eaf'),
      ('42915d5f-d954-4391-b9d3-79094a24b8c2:019e645f-b84c-7f0a-9076-c6059ac15a2e')
  ) AS t(session_key)
),
persona_conversations AS (
  SELECT DISTINCT m.conversation_id
  FROM pool p
  INNER JOIN toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data m
    ON concat(m.conversation_id, ':', m.session_id) = p.session_key
),
interactions AS (
  SELECT
    ix.interaction_id,
    ix.origin_id AS conversation_id,
    ix.message_created_at,
    ix.message_completed_at,
    ix.message_text_content,
    ix.response_text_content,
    ix.origin_title,
    ix.author.role AS author_role,
    ix.configuration.model_name AS model_name,
    size(coalesce(ix.full_tool_calls, array())) AS tool_call_count
  FROM toqan_analytics_internal.toqan_restaurants_pii.analytics_agents_interactions_restaurants_pii ix
  WHERE ix.platform_type = 'web'
    AND ix.origin_id IS NOT NULL
    AND trim(ix.origin_id) != ''
    AND ix.origin_id NOT IN (SELECT conversation_id FROM excluded_conversations)
),
conv_stats AS (
  SELECT
    pc.conversation_id,
    count(ix.interaction_id) AS total_turns,
    any_value(ix.origin_title) AS origin_title,
    max(ix.message_created_at) AS last_message_at
  FROM persona_conversations pc
  INNER JOIN interactions ix ON ix.conversation_id = pc.conversation_id
  GROUP BY pc.conversation_id
),
top_conversations AS (
  SELECT
    conversation_id,
    origin_title,
    total_turns,
    row_number() OVER (ORDER BY total_turns DESC, last_message_at DESC) AS conv_rank
  FROM conv_stats
  WHERE total_turns > 0
),
turns AS (
  SELECT
    tc.conv_rank,
    tc.conversation_id,
    tc.origin_title,
    tc.total_turns,
    row_number() OVER (
      PARTITION BY tc.conversation_id
      ORDER BY ix.message_created_at
    ) AS turn_number,
    ix.message_created_at,
    ix.author_role,
    ix.model_name,
    ix.tool_call_count,
    ix.message_text_content AS user_message,
    ix.response_text_content AS assistant_reply
  FROM top_conversations tc
  INNER JOIN interactions ix
    ON ix.conversation_id = tc.conversation_id
  WHERE tc.conv_rank <= 10
)
SELECT
  conv_rank,
  conversation_id,
  origin_title,
  total_turns,
  turn_number,
  message_created_at,
  author_role,
  model_name,
  tool_call_count,
  user_message,
  assistant_reply
FROM turns
ORDER BY conv_rank, turn_number;
