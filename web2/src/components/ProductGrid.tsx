import { products } from "../data/products";

const families = ["Plex Development", "Drako Development"] as const;

export const ProductGrid = () => (
  <div className="product-groups">
    {families.map((family) => (
      <section key={family} className="product-group" aria-labelledby={`${family.replace(" ", "-").toLowerCase()}-title`}>
        <h3 id={`${family.replace(" ", "-").toLowerCase()}-title`}>{family}</h3>
        <div className="product-list">
          {products.filter((product) => product.family === family).map((product) => (
            <article key={product.name} className="product-row">
              <div>
                <h4>{product.name}</h4>
                <p>{product.description}</p>
              </div>
              <span className="port">Default port {product.port}</span>
            </article>
          ))}
        </div>
      </section>
    ))}
  </div>
);
