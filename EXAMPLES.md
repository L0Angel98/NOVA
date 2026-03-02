# NOVA Examples v0.1.2

Ejemplos declarativos consistentes con `SPEC.md` (contrato minimo v0.1).

## 1) CRUD JSON

```nova
mdl users_api v"0.1.2" rst<any, err> {
  rte "/users" POST json {
    cap ["users.write"]
    tb users
    grd ctx.b, ctx.b.name, ctx.b.email : "BAD_REQUEST"
    rst.ok(db.create(ctx.b))
  }

  rte "/users" GET json {
    cap ["users.read"]
    tb users
    whe active == tru
    ord id asc
    if ctx.q.n == nul {
      lim num20
    } els {
      lim to_num(ctx.q.n)
    }
    rst.ok(db.read())
  }

  rte "/users/:id" PUT json {
    cap ["users.write"]
    tb users
    whe id == ctx.p.id
    grd ctx.b : "BAD_REQUEST"
    rst.ok(db.update(ctx.b))
  }

  rte "/users/:id" DEL json {
    cap ["users.write"]
    tb users
    whe id == ctx.p.id
    rst.ok(db.delete())
  }
}
```

## 2) CRUD TOON

```nova
mdl tickets_api v"0.1.2" rst<any, err> {
  rte "/tickets.toon" POST toon {
    cap ["tickets.write"]
    tb tickets
    grd ctx.b, ctx.b.title : "BAD_REQUEST"
    rst.ok(db.create(ctx.b))
  }

  rte "/tickets.toon" GET toon {
    cap ["tickets.read"]
    tb tickets
    whe status == "new"
    ord id desc
    lim num10
    rst.ok(db.read())
  }

  rte "/tickets/:id.toon" PAT toon {
    cap ["tickets.write"]
    tb tickets
    whe id == ctx.p.id
    grd ctx.b : "BAD_REQUEST"
    rst.ok(db.update(ctx.b))
  }

  rte "/tickets/:id.toon" DEL toon {
    cap ["tickets.write"]
    tb tickets
    whe id == ctx.p.id
    rst.ok(db.delete())
  }
}
```

Payload TOON tabular:

```toon
@toon v1
@type array
|id|title|status|
|1|"Error login mobile"|"new"|
|2|"Checkout timeout"|"resolved"|
```

## 3) `match` + `err`

```nova
mdl health_api v"0.1.2" rst<any, err> {
  rte "/health" GET json {
    let db_state = "degraded"

    let level = match db_state {
      "ok" => "green"
      "degraded" => "yellow"
      "down" => "red"
      _ => "unknown"
    }

    if level == "red" {
      err {
        code: "SERVICE_UNAVAILABLE"
        msg: "database is down"
      }
    } els {
      rst.ok({ status: level })
    }
  }
}
```

## 4) DB IR declarativo (`tb users.get` / `tb users.q`)

```nova
mdl users_db_ir v"0.1.2" rst<any, err> {
  rte "/users" GET json {
    tb users.get
    rst.ok(db.read())
  }

  rte "/users/top" GET json {
    tb users.q {
      whe active == tru
      ord created_at desc
      lim num5
    }
    rst.ok(db.read())
  }
}
```
