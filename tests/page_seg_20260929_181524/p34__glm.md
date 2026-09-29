例1-2 随机相位正弦波 $x(t) = A \sin(\omega_0 t + \varphi)$, $\varphi$ 在 $0 \sim 2\pi$ 之间均匀分布, 幅度 $A$ 为常数; 随机幅度正弦波 $y(t) = B \sin(\omega_0 t)$, $B$ 是与 $\varphi$ 相互独立的随机量, $B$ 的概率密度函数为

$$p(B) = \frac{1}{\sqrt{2\pi}} \exp[-B^2/2]$$

(1-33a)

试求 $x(t)$ 和 $y(t)$ 的统计特征量 $\mu_x, \sigma_x^2, R_x(\tau), \mu_y, R_{xy}(\tau)$ 和 $C_{xy}(\tau)$。

解：（1）$x(t)$ 的均值 $\mu_x$

$$\mu_x = E[x(t)] = \int x(t) p(x) \mathrm{d}x = \int_0^{2\pi} A \sin(\omega_0 t + \varphi) p(\varphi) \mathrm{d}\varphi$$

$$= \frac{A}{2\pi} \int_0^{2\pi} \sin(\omega_0 t + \varphi) \mathrm{d}\varphi = 0$$

(2) $x(t)$ 的方差 $\sigma_x^2$

$$\sigma_x^2 = E[x(t) - \mu_x]^2 = E[A^2 \sin^2(\omega_0 t + \varphi)]$$

$$= \frac{A^2}{2} E[1 - \cos(2\omega_0 t + 2\varphi)]$$

$$= \frac{A^2}{2} - \frac{A^2}{2} \frac{1}{2\pi} \int_0^{2\pi} \cos(2\omega_0 t + 2\varphi) \mathrm{d}\varphi = \frac{A^2}{2}$$

(3) $x(t)$ 的自相关函数 $R_x(\tau)$

$$R_x(\tau) = E[x(t) x(t - \tau)]$$

$$= E[A \sin(\omega_0 t + \varphi) A \sin(\omega_0 (t - \tau) + \varphi)]$$

$$= A^2 E[\sin(\omega_0 t + \varphi) \sin(\omega_0 (t - \tau) + \varphi)]$$

$$= \frac{A^2}{2} E[\cos(\omega_0 \tau) - \cos(\omega_0 (2t - \tau) + 2\varphi)]$$

$$= \frac{A^2}{2} \cos(\omega_0 \tau) - \frac{A^2}{2} \frac{1}{2\pi} \int_0^{2\pi} \cos(\omega_0 (2t - \tau) + 2\varphi) \mathrm{d}\varphi$$

上式右边的第二项积分结果为零，所以

$$R_x(\tau) = \frac{A^2}{2} \cos(\omega_0 \tau)$$

这也就证明了自相关函数的特点（4）：对于正弦信号，不管其初相位如何，其自相关函数总是以余弦函数的形式出现。

(4) $y(t)$ 的均值 $\mu_y$

对比式(1-12)与式(1-33a)可知，$y(t)$ 的幅值 $B$ 是高斯分布，其均值为零，方差为1，得

$$\mu_y = E[y(t)] = E[B \cos(\omega_0 t)] = E[B] E[\cos(\omega_0 t)] = 0$$

(5) 互相关函数 $R_{xy}(\tau)$ 和互协方差函数 $C_{xy}(\tau)$

因为 $B$ 和 $\varphi$ 相互独立，所以可得

$$R_{xy}(\tau) = E[x(t - \tau) y(t)]$$

$$= E[A \sin(\omega_0 (t - \tau) + \varphi) B \sin(\omega_0 t)]$$

$$= E[A \sin(\omega_0 (t - \tau) + \varphi)] E[B \sin(\omega_0 t)]$$

$$= \mu_x \mu_y = 0$$

$$C_{xy}(\tau) = R_{xy}(\tau) - \mu_x \mu_y = 0$$