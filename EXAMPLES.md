# NOVA Examples v0.1

Este archivo contiene ejemplos declarativos (no ejecutables) consistentes con `SPEC.md`.

## 1) CRUD JSON

```nova
mdl users_api v"0.1.0" rst<any, err> {
  rte "/users" POST json {
    cap ["users.write"]
    tb users
    grd body, body.name, body.email : "BAD_REQUEST"
    rst.ok(db.create(body))
  }

  rte "/users" GET json {
    cap ["users.read"]
    tb users
    whe active == tru
    ord id asc
    lim num20
    rst.ok(db.read())
  }

  rte "/users/:id" PUT json {
    cap ["users.write"]
    tb users
    whe id == params.id
    grd body : "BAD_REQUEST"
    rst.ok(db.update(body))
  }

  rte "/users/:id" DELETE json {
    cap ["users.write"]
    tb users
    whe id == params.id
    rst.ok(db.delete())
  }
}
```

## 2) CRUD TOON tabular

```nova
mdl tickets_api v"0.1.0" rst<any, err> {
  rte "/tickets.toon" POST toon {
    cap ["tickets.write"]
    tb tickets
    grd body, body.title : "BAD_REQUEST"
    rst.ok(db.create(body))
  }

  rte "/tickets.toon" GET toon {
    cap ["tickets.read"]
    tb tickets
    whe status == "new"
    ord id desc
    lim num10
    rst.ok(db.read())
  }

  rte "/tickets/:id.toon" PATCH toon {
    cap ["tickets.write"]
    tb tickets
    whe id == params.id
    grd body : "BAD_REQUEST"
    rst.ok(db.update(body))
  }

  rte "/tickets/:id.toon" DELETE toon {
    cap ["tickets.write"]
    tb tickets
    whe id == params.id
    rst.ok(db.delete())
  }
}
```

Ejemplo de payload TOON tabular:

```toon
@toon v1
@type array
|id|title|status|
|1|"Error login mobile"|"new"|
|2|"Checkout timeout"|"resolved"|
```

## 3) Ejemplo con `match`

```nova
mdl health_api v"0.1.0" rst<any, err> {
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
      rst.ok({
        status: level
      })
    }
  }
}
```

## 4) DB IR declarativo (`tb users.get` / `tb users.q`)

```nova
mdl users_db_ir v"0.1.0" rst<any, err> {
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
