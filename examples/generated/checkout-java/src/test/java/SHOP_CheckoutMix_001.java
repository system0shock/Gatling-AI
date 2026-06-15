import io.gatling.javaapi.core.ChainBuilder;
import io.gatling.javaapi.core.ScenarioBuilder;
import io.gatling.javaapi.core.Simulation;
import io.gatling.javaapi.http.HttpProtocolBuilder;
import java.time.Duration;

import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

public class SHOP_CheckoutMix_001 extends Simulation {

  private static String requiredEnv(String name) {
    String value = System.getenv(name);
    if (value == null || value.isBlank()) {
      throw new IllegalStateException("Missing required environment variable: " + name);
    }
    return value;
  }

  private final HttpProtocolBuilder httpProtocol = http.baseUrl(requiredEnv("BASE_URL"));

  private final ChainBuilder openProducts =
    exec(
          http("01 catalog.open-products - Open product list")
            .get("/products")
            .check(status().is(200))
            .check(jsonPath("$.items[0].id").saveAs("productId"))
    );

  private final ChainBuilder gqlPrice =
    exec(
          http("02 catalog.gql-price - Fetch price via GraphQL")
            .post("/graphql")
            .header("Content-Type", "application/json")
            .body(StringBody("{\"query\":\"query($id:ID!){ price(id:$id){ amount } }\",\"variables\":{\"id\":\"#{productId}\"}}"))
            .check(status().is(200))
    );

  private final ChainBuilder submitCheckout =
    exec(
          http("03 checkout.submit - Submit checkout")
            .post("/checkout")
            .header("Content-Type", "application/json")
            .body(StringBody("{\"productId\":\"#{productId}\"}"))
            .check(status().is(200))
    );

  private final ChainBuilder searchProducts =
    exec(
          http("04 search.query - Search products")
            .get("/search?q=#{term}")
            .check(status().is(200))
    );

  private final ScenarioBuilder mainCheckout = scenario("main-checkout")
    .feed(csv("terms.csv").circular())
    .group("01 catalog.open-products - Open product list").on(openProducts).pause(Duration.ofSeconds(1))
    .group("02 catalog.gql-price - Fetch price via GraphQL").on(gqlPrice)
    .group("03 checkout.submit - Submit checkout").on(submitCheckout);

  private final ScenarioBuilder backgroundSearch = scenario("background-search")
    .feed(csv("terms.csv").circular())
    .group("04 search.query - Search products").on(searchProducts);

  {
    setUp(
      mainCheckout.injectClosed(
        incrementConcurrentUsers(5).times(2).eachLevelLasting(Duration.ofSeconds(30)).startingFrom(5)
      ),
      backgroundSearch.injectOpen(
        constantUsersPerSec(2).during(Duration.ofSeconds(60))
      )
    ).protocols(httpProtocol)
      .assertions(
        global().responseTime().percentile(95.0).lt(800),
        global().successfulRequests().percent().gt(99.0)
      );
  }
}
