# Deployment evidence

**Date:** 2026-07-27
**What this records:** one live deployment of the Terraform module in
`deploy/terraform/` into a dedicated AWS account, a set of queries run through
the load balancer, and a same-day teardown.

**Configuration deployed:** the default one — `enable_egress = true`,
`llm_provider = "anthropic"`. That is 34 resources. The air-gapped Bedrock
configuration is 36 resources and is **not** covered by this document; it is
waiting on an AWS service quota request. See `deploy/README.md` for the
difference between the two.

The AWS account id is redacted throughout. This repository is public, and while
an account id is not a credential, there is no reason to publish it.

---

## 1. Plan

The module was planned against an empty account with a saved plan file, so that
the apply executed exactly what was reviewed.

```
Plan: 34 to add, 0 to change, 0 to destroy.
```

---

## 2. Apply, confirmed against state rather than against the console

The apply summary line is the convenient thing to record. The authoritative
thing is what Terraform's state actually contains afterwards, so that is what is
recorded here.

```
$ terraform state list | wc -l
      36

$ echo "data sources: $(terraform state list | grep -c '^data\.')"
data sources: 2

$ echo "resources:    $(terraform state list | grep -vc '^data\.')"
resources:    34
```

36 and 34 are both correct answers to different questions. A `data` block reads
something that already exists rather than creating it, so it is stored in state
and listed by `state list`, but it never appears in `Plan: N to add`. The two
data sources here are the caller identity and region lookups. Netting them out
reconciles the state against the plan exactly: 34 managed resources, matching
the 34 that were planned.

---

## 3. Health check through the load balancer

The target group health check hits `/api/health` with a matcher of `200`. The
application returns **503** while the vector index is still building and 200
only once it can actually answer, so the load balancer will not route traffic to
a container that is running but not ready.

```
$ curl -i "http://$ALB/api/health"

HTTP/1.1 200 OK
Date: Mon, 27 Jul 2026 19:40:26 GMT
Content-Type: application/json
Content-Length: 15
Connection: keep-alive
server: uvicorn

{"status":"ok"}
```

---

## 4. The permission gate, same question, two callers

This is the pair that matters. The same question is asked twice against the same
running container, changing only the caller's permissions. The document holding
the answer, `hr-001`, is tagged `permissions: [hr]` in the corpus manifest.

The first caller is answered from the corpus with a citation carrying the
document id, the section path, and the exact character offsets of the span the
answer came from.

```
$ curl -s -X POST "http://$ALB/api/chat" -H 'Content-Type: application/json' \
    -d '{"query":"What is James Santos salary and start date?","user_permissions":["hr"]}'

{
    "answer": "Based on the employee records, James Santos has the following details:\n\n- **Salary:** $53,000/year\n- **Start Date:** March 2, 2022",
    "citations": [
        {
            "doc_id": "hr-001",
            "doc_name": "hr-001",
            "section_path": [
                "HR Employee Records -- CONFIDENTIAL",
                "Employee 1: James Santos"
            ],
            "char_start": 146,
            "char_end": 478,
            "snippet": "## Employee 1: James Santos\n\n- **Full Name:** James Santos\n- **Email:** james.santos@example.org\n- **Phone:** (555) 555-0100\n- **SSN:** 900-55-0000\n- **Date of Birth:** 1990-07-29\n- **Address:** 200 T..."
        }
    ],
    "refused": false
}
```

The second caller is refused.

```
$ curl -s -X POST "http://$ALB/api/chat" -H 'Content-Type: application/json' \
    -d '{"query":"What is James Santos salary and start date?","user_permissions":["general"]}'

{
    "answer": "I don't have information about that in the available documents. The retrieved excerpts do not contain any details about individual employee records such as salary or start dates for James Santos or any other employee.",
    "citations": [],
    "refused": true
}
```

Read the second response carefully, because the wording is the point: *"the
retrieved excerpts do not contain any details about individual employee
records."* The `general` caller was not shown the restricted document and
instructed to decline. The document was filtered out of the vector query, so
those chunks were never in the model's context at all.

That is the distinction this project exists to make. A permission rule written
into a system prompt is an instruction the model may or may not follow. A
permission filter applied to retrieval is arithmetic that has already happened
by the time the model is invoked. The model cannot disclose what it was never
given, and it cannot be argued out of a filter that ran before it was called.

All PII in the corpus is synthetic by construction: RFC 2606 example.org
addresses, ITU-T 555-0100 through 555-0199 phone numbers, and never-issued 900-
series SSN areas. No value in it can match a real person.

---

## 5. Container logs

Lines from the task's own CloudWatch log group, `/ecs/custos-demo`, covering the
requests above.

```
19:40:39 qdrant  "POST /collections/custos/points/query HTTP/1.1" 200 783  0.004246
19:40:42 custos  10.40.15.249:35996 - "POST /api/chat HTTP/1.1" 200 OK
19:42:15 qdrant  "POST /collections/custos/points/query HTTP/1.1" 200 1098 0.008086
19:42:20 custos  10.40.15.249:38894 - "POST /api/chat HTTP/1.1" 200 OK
19:42:21 qdrant  "POST /collections/custos/points/query HTTP/1.1" 200 913  0.001496
19:42:23 custos  10.40.27.140:29800 - "POST /api/chat HTTP/1.1" 200 OK
```

Three things worth reading out of those six lines. Every chat request is
preceded by a vector query answered locally in 1.5 to 8 milliseconds, over
loopback, because Qdrant runs as a sidecar in the same task rather than as a
network service. The two source addresses, `10.40.15.249` and `10.40.27.140`,
are the load balancer's nodes in two different availability zones, which is the
multi-AZ claim demonstrated from the application's own logs rather than asserted
from the Terraform. And the health check log, trimmed out here for length, shows
both of those addresses polling `/api/health` every ten seconds throughout.

A redeploy performed during this session also produced a clean drain of the
outgoing task:

```
19:44:50 custos/0bf631b45ad2  INFO:     Shutting down
19:44:50 custos/0bf631b45ad2  INFO:     Waiting for application shutdown.
19:44:50 custos/0bf631b45ad2  INFO:     Application shutdown complete.
19:44:50 custos/0bf631b45ad2  INFO:     Finished server process [1]
```

---

## 6. Destroy, and the confirmation that nothing kept billing

Torn down the same day. "I ran destroy" and "nothing is billing" are not the
same statement, so the destroy summary is recorded alongside an explicit check
for the two resources that cost real money when they survive: the NAT gateway
and the load balancer. Both queries should return empty.

```
Plan: 0 to add, 0 to change, 34 to destroy.

Destroy complete! Resources: 34 destroyed.
```

The counts line up on the way out as well as on the way in: 34 planned, 34 in
state, 34 destroyed.

Then the checks. Both of these return nothing, and the empty result is the
evidence.

```
$ aws ec2 describe-nat-gateways \
    --filter "Name=state,Values=available,pending" \
    --query 'NatGateways[].NatGatewayId' --output text

$ aws elbv2 describe-load-balancers \
    --query 'LoadBalancers[].LoadBalancerName' --output text
```

Those two are the resources in this stack that bill by the hour whether or not
anything is using them, so they are the two worth asking about directly rather
than inferring from a successful destroy.

The destroy timings are also worth reading, because they are the dependency
graph made visible. The ECS service took 7m10s, draining connections before
removing itself. The internet gateway took 6m55s, because it cannot detach until
the NAT gateway's elastic network interface releases. The NAT gateway itself
took 41s and the load balancer 27s. Everything else finished in under a second.
Terraform is not slow here; it is waiting on AWS to release things in an order
that keeps the network consistent while it comes apart.

The destroy also ran the module's two guard rails in reverse —
`terraform_data.account_guard` and `terraform_data.egress_provider_guard` — which
assert the target account id and the configured LLM provider before anything is
touched. They exist so that a misconfigured `terraform apply` fails on a string
comparison rather than in someone else's account.

The Secrets Manager secret is created with a 30-day recovery window, so
`terraform destroy` only *schedules* its deletion. The value persists and the
name stays reserved for those 30 days, which is a sensible default and a
surprising one if you assume destroy means gone. It was removed explicitly:

```
$ aws secretsmanager delete-secret --secret-id custos/demo/llm-api-key \
    --force-delete-without-recovery --query 'Name' --output text
custos/demo/llm-api-key
```

---

## What this demonstrates, and what it does not

It demonstrates that the module in this repository stands up a working,
network-isolated deployment in a real AWS account from a clean state, that the
permission gate holds against a live HTTP request rather than only in tests, and
that the whole thing tears back down cleanly.

It does not demonstrate an air-gapped deployment. That is the Bedrock
configuration, it is a different resource count, and it has not been run.
